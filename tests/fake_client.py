"""
An in-memory stand-in for olca_ipc.Client.

It holds olca_schema objects in dictionaries and implements the part of
the client that the olcaBASIC engine uses: get_descriptors,
get_descriptor, get, get_all, find, put, delete, get_parameters,
get_providers, create_product_system and calculate.

Calculations are small but real. Each background process carries canned
"direct impacts" per unit of its reference output; foreground processes
add up their inputs through the provider links, with exchange formulas
and parameters evaluated (and parameter redefinitions applied). So
scenarios and sensitivity runs change the numbers the way they do in
openLCA, and the results are deterministic.

Everything in the seeded database is synthetic. The names are shaped
like ecoinvent names (several processes share one name and differ only
by location, as they do there) but none of them is a real dataset.
"""

import copy
import math
import random
import re
import uuid
from typing import Dict, List, Optional

import olca_schema as o


def _uid(*parts) -> str:
    """A stable UUID from a name, so seeded ids are the same every run."""
    return str(uuid.uuid5(uuid.NAMESPACE_URL, "olcabasic-fake/" + "/".join(parts)))


_FORMULA_FUNCS = {
    "abs": abs, "min": min, "max": max, "sqrt": math.sqrt, "ln": math.log,
    "log": math.log10, "exp": math.exp, "sin": math.sin, "cos": math.cos,
    "tan": math.tan, "round": round, "floor": math.floor, "ceil": math.ceil,
    "pow": pow, "pi": math.pi,
}


class FormulaError(Exception):
    pass


def eval_formula(formula: str, lookup) -> float:
    """Evaluate an openLCA-style formula. lookup(name) returns a value."""
    expr = formula.replace("^", "**")

    class _Names(dict):
        def __missing__(self, key):
            if key in _FORMULA_FUNCS:
                return _FORMULA_FUNCS[key]
            value = lookup(key)
            if value is None:
                raise FormulaError(f"unknown parameter '{key}' in '{formula}'")
            return value

    try:
        return float(eval(expr, {"__builtins__": {}}, _Names()))
    except FormulaError:
        raise
    except Exception as e:  # pragma: no cover - reported to the caller
        raise FormulaError(f"cannot evaluate '{formula}': {e}")


class FakeResult:
    """Stand-in for olca_ipc's Result object.

    The model is linear and has no loops, so every number can be checked
    by hand: a process's scaling factor is the amount of its reference
    product the system needs divided by the reference amount; direct
    results are what the process's own exchanges give at that scaling;
    total (upstream) results add everything that supplies it; an
    intensity is the total result of one unit of the reference product.
    """

    def __init__(self, client: "FakeClient", system, method, redefs,
                 setup=None, simulation: bool = False):
        self.client = client
        self.system = system
        self.method = method
        self.redefs = list(redefs or [])
        self.setup = setup
        self.simulation = simulation
        self.uid = str(uuid.uuid4())
        self.error = None
        self.disposed = False
        self._run = 0
        self._rng = random.Random(12345)
        self._jitter = 1.0
        self._sampling = False
        self._compute()

    # ── evaluation ───────────────────────────────────────────

    def _categories(self) -> List[o.ImpactCategory]:
        if self.method is None:
            return []
        method = self.client.store["ImpactMethod"].get(self.method.id)
        cats = []
        for ref in (method.impact_categories or []) if method else []:
            cat = self.client.store["ImpactCategory"].get(ref.id)
            if cat:
                cats.append(cat)
        return cats

    def _sample(self, value, unc):
        """One draw from an uncertainty distribution (Monte Carlo runs
        only); the plain value otherwise."""
        if not self._sampling or unc is None or unc.distribution_type is None:
            return value
        t = unc.distribution_type
        if t == o.UncertaintyType.UNIFORM_DISTRIBUTION:
            return self._rng.uniform(unc.minimum, unc.maximum)
        if t == o.UncertaintyType.TRIANGLE_DISTRIBUTION:
            return self._rng.triangular(unc.minimum, unc.maximum, unc.mode)
        if t == o.UncertaintyType.NORMAL_DISTRIBUTION:
            return self._rng.gauss(unc.mean, unc.sd)
        if t == o.UncertaintyType.LOG_NORMAL_DISTRIBUTION:
            return self._rng.lognormvariate(math.log(unc.geom_mean),
                                            math.log(unc.geom_sd))
        return value

    def _global_value(self, name, _seen=()):
        for r in self.redefs:
            if r.name == name and r.context is None:
                return r.value
        for p in self.client.store["Parameter"].values():
            if p.name == name:
                if p.formula and not p.is_input_parameter:
                    if name in _seen:
                        raise FormulaError(f"circular parameter '{name}'")
                    return eval_formula(
                        p.formula, lambda n: self._global_value(n, _seen + (name,)))
                key = ("global", name)
                if key not in self._samples:
                    self._samples[key] = self._sample(p.value, p.uncertainty)
                return self._samples[key]
        return None

    def _process_value(self, proc, name, _seen=()):
        for r in self.redefs:
            if r.name == name and r.context is not None and r.context.id == proc.id:
                return r.value
        for p in proc.parameters or []:
            if p.name == name:
                if p.formula and not p.is_input_parameter:
                    if name in _seen:
                        raise FormulaError(f"circular parameter '{name}'")
                    return eval_formula(
                        p.formula,
                        lambda n: self._process_value(proc, n, _seen + (name,)))
                key = (proc.id, name)
                if key not in self._samples:
                    self._samples[key] = self._sample(p.value, p.uncertainty)
                return self._samples[key]
        return self._global_value(name)

    def _unit_factor(self, unit_ref) -> float:
        if unit_ref is not None:
            unit = self.client.unit_by_id.get(unit_ref.id)
            if unit is not None and unit.conversion_factor:
                return unit.conversion_factor
        return 1.0

    def _amount(self, proc, ex) -> float:
        """Exchange amount in the reference unit of its flow property."""
        key = (proc.id, "ex", ex.internal_id)
        if key in self._samples:
            return self._samples[key]
        if ex.amount_formula:
            amount = eval_formula(
                ex.amount_formula, lambda n: self._process_value(proc, n))
        else:
            amount = ex.amount or 0.0
        amount = self._sample(amount, ex.uncertainty)
        amount *= self._unit_factor(ex.unit)
        self._samples[key] = amount
        return amount

    def _provider_of(self, proc, ex) -> Optional[str]:
        # As in openLCA, a link belongs to one exchange: two inputs of
        # the same flow can have different providers.
        fallback = None
        for link in self.system.process_links or []:
            if (link.process and link.process.id == proc.id
                    and link.flow and ex.flow and link.flow.id == ex.flow.id
                    and link.provider):
                if link.exchange is None:
                    fallback = fallback or link.provider.id
                elif link.exchange.internal_id == ex.internal_id:
                    return link.provider.id
        return fallback

    def _qref(self, proc):
        for ex in proc.exchanges or []:
            if ex.is_quantitative_reference:
                return ex
        return None

    def _allocation(self):
        return getattr(self.setup, "allocation", None) if self.setup else None

    def _allocation_factor(self, proc, qref) -> float:
        """Share of a multi-output process's burdens given to its
        reference product under the allocation of this calculation."""
        alloc = self._allocation()
        if alloc in (None, o.AllocationType.NO_ALLOCATION):
            return 1.0
        if alloc == o.AllocationType.USE_DEFAULT_ALLOCATION:
            alloc = proc.default_allocation_method
            if alloc in (None, o.AllocationType.NO_ALLOCATION,
                         o.AllocationType.USE_DEFAULT_ALLOCATION):
                return 1.0
        for f in proc.allocation_factors or []:
            if (f.allocation_type == alloc and f.product and qref is not None
                    and qref.flow and f.product.id == qref.flow.id
                    and f.exchange is None):
                return f.value if f.value is not None else 1.0
        return 1.0

    def _cost_of(self, ex) -> float:
        """Cost of an exchange in the reference currency."""
        if ex.cost_value is None:
            return 0.0
        rate = 1.0
        if ex.currency is not None:
            cur = self.client.store["Currency"].get(ex.currency.id)
            if cur is not None and cur.conversion_factor:
                rate = cur.conversion_factor
        return ex.cost_value * rate

    def _compute(self):
        """Walk the system from the reference process, accumulating the
        total requirement of every process and the totals per category."""
        cats = self._categories()
        self.cat_refs = [o.Ref(id=c.id, name=c.name, ref_unit=c.ref_unit,
                               ref_type=o.RefType.ImpactCategory) for c in cats]
        factors = {}   # category id -> {flow id: value}
        for c in cats:
            factors[c.id] = {f.flow.id: (f.value or 0.0)
                             for f in (c.impact_factors or []) if f.flow}
        self._samples: Dict[tuple, float] = {}
        self._per_unit_cache: Dict[str, Dict[str, float]] = {}
        self._direct_per_unit: Dict[str, Dict[str, float]] = {}
        self._flows_direct: Dict[str, Dict[tuple, float]] = {}
        self._flows_per_unit: Dict[str, Dict[tuple, float]] = {}
        self._cost_direct: Dict[str, float] = {}
        self._cost_per_unit: Dict[str, float] = {}
        self._children: Dict[str, List[tuple]] = {}
        self._qamount: Dict[str, float] = {}
        self._column: Dict[str, List[tuple]] = {}
        self.requirements: Dict[str, float] = {}
        self.envi_totals: Dict[tuple, float] = {}
        self._factors = factors
        self._cats = cats

        root = self.client.store["Process"].get(self.system.ref_process.id)
        if root is None:
            raise RuntimeError("reference process of the system is missing")
        target = self.system.target_amount
        if target is None or target == 0:
            target = 1.0
        target_unit = self.system.target_unit
        if self.setup is not None and getattr(self.setup, "amount", None):
            target = self.setup.amount
            if getattr(self.setup, "unit", None) is not None:
                target_unit = self.setup.unit
        target *= self._unit_factor(target_unit)
        self.demand = target
        self.root = root
        self.totals = {c.id: 0.0 for c in cats}
        per_unit = self._per_unit(root.id, ())
        for cid in self.totals:
            self.totals[cid] = per_unit.get(cid, 0.0) * target * self._jitter
        self._accumulate(root.id, target, ())

    def _per_unit(self, pid: str, path) -> Dict[str, float]:
        """Upstream impacts of one unit of a process's reference output."""
        if pid in self._per_unit_cache:
            return self._per_unit_cache[pid]
        proc = self.client.store["Process"].get(pid)
        result = {c.id: 0.0 for c in self._cats}
        direct = {c.id: 0.0 for c in self._cats}
        flows: Dict[tuple, float] = {}
        cost = 0.0
        children = []
        column = []
        if proc is None or pid in path:
            return result
        qref = self._qref(proc)
        qamount = self._amount(proc, qref) if qref is not None else 1.0
        if not qamount:
            qamount = 1.0
        share_of_burden = self._allocation_factor(proc, qref)
        canned = self.client.direct_impacts.get(pid, {})
        for c in self._cats:
            direct[c.id] += canned.get(c.name, 0.0) / qamount
        if qref is not None:
            cost -= self._cost_of(qref) / qamount       # revenue
            column.append((pid, qamount))
        for ex in proc.exchanges or []:
            if ex is qref or ex.flow is None:
                continue
            amount = self._amount(proc, ex) * share_of_burden
            flow = self.client.store["Flow"].get(ex.flow.id)
            if flow is not None and flow.flow_type == o.FlowType.ELEMENTARY_FLOW:
                key = (flow.id, bool(ex.is_input))
                flows[key] = flows.get(key, 0.0) + amount / qamount
                for c in self._cats:
                    cf = self._factors[c.id].get(flow.id)
                    if cf:
                        direct[c.id] += amount * cf / qamount
                continue
            money = self._cost_of(ex) * share_of_burden / qamount
            avoided = bool(ex.is_avoided_product)
            is_cost = bool(ex.is_input) != avoided
            cost += money if is_cost else -money
            provider = self._provider_of(proc, ex)
            if provider is None:
                continue
            share = amount / qamount
            if avoided:
                share = -share
            children.append((provider, share))
            column.append((provider, -share * qamount))
            up = self._per_unit(provider, path + (pid,))
            for cid, v in up.items():
                result[cid] += share * v
        for cid in result:
            result[cid] += direct[cid]
        total_flows = dict(flows)
        total_cost = cost
        for provider, share in children:
            for key, v in self._flows_per_unit.get(provider, {}).items():
                total_flows[key] = total_flows.get(key, 0.0) + share * v
            total_cost += share * self._cost_per_unit.get(provider, 0.0)
        self._per_unit_cache[pid] = result
        self._direct_per_unit[pid] = direct
        self._flows_direct[pid] = flows
        self._flows_per_unit[pid] = total_flows
        self._cost_direct[pid] = cost
        self._cost_per_unit[pid] = total_cost
        self._children[pid] = children
        self._qamount[pid] = qamount
        self._column[pid] = column
        return result

    def _accumulate(self, pid, amount, path):
        if pid in path:
            return
        self.requirements[pid] = self.requirements.get(pid, 0.0) + amount
        for key, v in self._flows_direct.get(pid, {}).items():
            self.envi_totals[key] = self.envi_totals.get(key, 0.0) + amount * v
        for provider, share in self._children.get(pid, []):
            self._accumulate(provider, amount * share, path + (pid,))

    def _tech_flow(self, pid) -> o.TechFlow:
        proc = self.client.store["Process"].get(pid)
        qref = self._qref(proc) if proc else None
        flow = (o.Ref(id=qref.flow.id, name=self.client._flow_name(qref.flow.id),
                      ref_type=o.RefType.Flow) if qref and qref.flow else None)
        return o.TechFlow(
            provider=o.Ref(id=pid, name=proc.name if proc else "?",
                           location=(self.client._location_code(proc.location)
                                     or None) if proc else None,
                           ref_type=o.RefType.Process),
            flow=flow)

    def _envi_flow(self, key) -> o.EnviFlow:
        fid, is_input = key
        flow = self.client.store["Flow"].get(fid)
        return o.EnviFlow(
            flow=o.Ref(id=fid, name=flow.name if flow else "?",
                       category=flow.category if flow else "",
                       ref_unit=self.client._ref_unit_of_flow(flow),
                       ref_type=o.RefType.Flow),
            is_input=is_input)

    def _values(self, amounts: Dict[str, float]) -> List[o.ImpactValue]:
        return [o.ImpactValue(amount=amounts.get(r.id, 0.0), impact_category=r)
                for r in self.cat_refs]

    def _flow_values(self, amounts: Dict[tuple, float]) -> List[o.EnviFlowValue]:
        return [o.EnviFlowValue(amount=amounts.get(key, 0.0),
                                envi_flow=self._envi_flow(key))
                for key in self.envi_totals]

    def _check(self):
        if self.disposed:
            raise RuntimeError("result was already disposed")
        self.client.calls.append(("result", self.uid))

    def _need(self, tech_flow) -> float:
        return self.requirements.get(tech_flow.provider.id, 0.0)

    def _key(self, envi_flow) -> tuple:
        return (envi_flow.flow.id, bool(envi_flow.is_input))

    def _cat(self, impact_ref) -> str:
        return impact_ref.id

    def _currency(self) -> Optional[o.Ref]:
        for cur in self.client.store["Currency"].values():
            if cur.ref_currency is None or cur.ref_currency.id == cur.id:
                return o.Ref(id=cur.id, name=cur.name,
                             ref_type=o.RefType.Currency)
        return None

    def _cost_value(self, amount) -> o.CostValue:
        return o.CostValue(amount=amount, currency=self._currency())

    # ── the Result API ───────────────────────────────────────

    def wait_until_ready(self):
        self._check()
        return o.ResultState(id=self.uid, is_ready=True)

    def get_state(self):
        return o.ResultState(id=self.uid, is_ready=True)

    def dispose(self):
        self.disposed = True

    def get_demand(self) -> o.TechFlowValue:
        self._check()
        return o.TechFlowValue(amount=self.demand,
                               tech_flow=self._tech_flow(self.root.id))

    def get_tech_flows(self) -> List[o.TechFlow]:
        self._check()
        return [self._tech_flow(pid) for pid in self.requirements]

    def get_envi_flows(self) -> List[o.EnviFlow]:
        self._check()
        return [self._envi_flow(key) for key in self.envi_totals]

    def get_impact_categories(self) -> List[o.Ref]:
        self._check()
        return list(self.cat_refs)

    # technosphere

    def get_total_requirements(self) -> List[o.TechFlowValue]:
        self._check()
        return [o.TechFlowValue(amount=v, tech_flow=self._tech_flow(pid))
                for pid, v in self.requirements.items()]

    def get_total_requirements_of(self, tech_flow) -> o.TechFlowValue:
        self._check()
        return o.TechFlowValue(amount=self._need(tech_flow), tech_flow=tech_flow)

    def get_scaling_factors(self) -> List[o.TechFlowValue]:
        self._check()
        return [o.TechFlowValue(amount=v / self._qamount.get(pid, 1.0),
                                tech_flow=self._tech_flow(pid))
                for pid, v in self.requirements.items()]

    def _column_of(self, tech_flow, scaled: bool) -> List[o.TechFlowValue]:
        pid = tech_flow.provider.id
        s = (self.requirements.get(pid, 0.0) / self._qamount.get(pid, 1.0)
             if scaled else 1.0)
        return [o.TechFlowValue(amount=v * s, tech_flow=self._tech_flow(other))
                for other, v in self._column.get(pid, [])]

    def get_scaled_tech_flows_of(self, tech_flow) -> List[o.TechFlowValue]:
        self._check()
        return self._column_of(tech_flow, True)

    def get_unscaled_tech_flows_of(self, tech_flow) -> List[o.TechFlowValue]:
        self._check()
        return self._column_of(tech_flow, False)

    # inventory

    def get_total_flows(self) -> List[o.EnviFlowValue]:
        self._check()
        return self._flow_values(self.envi_totals)

    def get_total_flow_value_of(self, envi_flow) -> o.EnviFlowValue:
        self._check()
        return o.EnviFlowValue(
            amount=self.envi_totals.get(self._key(envi_flow), 0.0),
            envi_flow=envi_flow)

    def get_flow_contributions_of(self, envi_flow) -> List[o.TechFlowValue]:
        self._check()
        key = self._key(envi_flow)
        return [o.TechFlowValue(
                    amount=self._flows_direct.get(pid, {}).get(key, 0.0) * need,
                    tech_flow=self._tech_flow(pid))
                for pid, need in self.requirements.items()]

    def get_direct_interventions_of(self, tech_flow) -> List[o.EnviFlowValue]:
        self._check()
        need = self._need(tech_flow)
        direct = self._flows_direct.get(tech_flow.provider.id, {})
        return self._flow_values({k: v * need for k, v in direct.items()})

    def get_direct_intervention_of(self, envi_flow, tech_flow) -> o.EnviFlowValue:
        self._check()
        v = self._flows_direct.get(tech_flow.provider.id, {}).get(
            self._key(envi_flow), 0.0)
        return o.EnviFlowValue(amount=v * self._need(tech_flow),
                               envi_flow=envi_flow)

    def get_flow_intensities_of(self, tech_flow) -> List[o.EnviFlowValue]:
        self._check()
        return self._flow_values(
            self._flows_per_unit.get(tech_flow.provider.id, {}))

    def get_flow_intensity_of(self, envi_flow, tech_flow) -> o.EnviFlowValue:
        self._check()
        v = self._flows_per_unit.get(tech_flow.provider.id, {}).get(
            self._key(envi_flow), 0.0)
        return o.EnviFlowValue(amount=v, envi_flow=envi_flow)

    def get_total_interventions_of(self, tech_flow) -> List[o.EnviFlowValue]:
        self._check()
        need = self._need(tech_flow)
        per = self._flows_per_unit.get(tech_flow.provider.id, {})
        return self._flow_values({k: v * need for k, v in per.items()})

    def get_total_intervention_of(self, envi_flow, tech_flow) -> o.EnviFlowValue:
        self._check()
        v = self._flows_per_unit.get(tech_flow.provider.id, {}).get(
            self._key(envi_flow), 0.0)
        return o.EnviFlowValue(amount=v * self._need(tech_flow),
                               envi_flow=envi_flow)

    # impacts

    def get_total_impacts(self) -> List[o.ImpactValue]:
        self._check()
        return self._values(self.totals)

    def get_total_impact_value_of(self, impact_category) -> o.ImpactValue:
        self._check()
        return o.ImpactValue(amount=self.totals.get(impact_category.id, 0.0),
                             impact_category=impact_category)

    def _nw(self):
        ref = getattr(self.setup, "nw_set", None) if self.setup else None
        if ref is None or self.method is None:
            return None
        method = self.client.store["ImpactMethod"].get(self.method.id)
        return next((n for n in (method.nw_sets or []) if n.id == ref.id), None)

    def _nw_values(self, weighted: bool) -> List[o.ImpactValue]:
        nw = self._nw()
        if nw is None:
            return []
        out = {}
        for f in nw.factors or []:
            cid = f.impact_category.id
            total = self.totals.get(cid, 0.0)
            norm = total / f.normalisation_factor if f.normalisation_factor else 0.0
            out[cid] = norm * (f.weighting_factor or 0.0) if weighted else norm
        return self._values(out)

    def get_normalized_impacts(self) -> List[o.ImpactValue]:
        self._check()
        return self._nw_values(False)

    def get_weighted_impacts(self) -> List[o.ImpactValue]:
        self._check()
        return self._nw_values(True)

    def get_impact_contributions_of(self, impact_category) -> List[o.TechFlowValue]:
        """Direct contribution of every process to one category."""
        self._check()
        cid = impact_category.id
        return [o.TechFlowValue(
                    amount=self._direct_per_unit.get(pid, {}).get(cid, 0.0) * need,
                    tech_flow=self._tech_flow(pid))
                for pid, need in self.requirements.items()]

    def get_total_impacts_of(self, tech_flow) -> List[o.ImpactValue]:
        self._check()
        pid = tech_flow.provider.id
        need = self.requirements.get(pid, 0.0)
        per_unit = self._per_unit_cache.get(pid, {})
        return self._values({cid: v * need * self._jitter
                             for cid, v in per_unit.items()})

    def get_total_impact_of(self, impact_category, tech_flow) -> o.ImpactValue:
        self._check()
        pid = tech_flow.provider.id
        v = self._per_unit_cache.get(pid, {}).get(impact_category.id, 0.0)
        return o.ImpactValue(amount=v * self._need(tech_flow) * self._jitter,
                             impact_category=impact_category)

    def get_direct_impacts_of(self, tech_flow) -> List[o.ImpactValue]:
        self._check()
        pid = tech_flow.provider.id
        need = self.requirements.get(pid, 0.0)
        direct = self._direct_per_unit.get(pid, {})
        return self._values({cid: v * need for cid, v in direct.items()})

    def get_direct_impact_of(self, impact_category, tech_flow) -> o.ImpactValue:
        self._check()
        v = self._direct_per_unit.get(tech_flow.provider.id, {}).get(
            impact_category.id, 0.0)
        return o.ImpactValue(amount=v * self._need(tech_flow),
                             impact_category=impact_category)

    def get_impact_intensities_of(self, tech_flow) -> List[o.ImpactValue]:
        """The real client sends a method name no server has, and so
        returns nothing: the fake does the same, so that code relying on
        it fails here as it would live."""
        self._check()
        return []

    def _intensities(self, tech_flow) -> List[o.ImpactValue]:
        return self._values(self._per_unit_cache.get(tech_flow.provider.id, {}))

    def get_impact_intensity_of(self, impact_category, tech_flow) -> o.ImpactValue:
        self._check()
        v = self._per_unit_cache.get(tech_flow.provider.id, {}).get(
            impact_category.id, 0.0)
        return o.ImpactValue(amount=v, impact_category=impact_category)

    def get_impact_factors_of(self, impact_category) -> List[o.EnviFlowValue]:
        self._check()
        f = self._factors.get(impact_category.id, {})
        return [o.EnviFlowValue(amount=f.get(key[0], 0.0),
                                envi_flow=self._envi_flow(key))
                for key in self.envi_totals]

    def get_impact_factor_of(self, impact_category, envi_flow) -> o.EnviFlowValue:
        self._check()
        f = self._factors.get(impact_category.id, {})
        return o.EnviFlowValue(amount=f.get(envi_flow.flow.id, 0.0),
                               envi_flow=envi_flow)

    def get_flow_impacts_of(self, impact_category) -> List[o.EnviFlowValue]:
        """What each elementary flow of the inventory gives to one
        category: total amount times its factor."""
        self._check()
        f = self._factors.get(impact_category.id, {})
        return [o.EnviFlowValue(amount=v * f.get(key[0], 0.0),
                                envi_flow=self._envi_flow(key))
                for key, v in self.envi_totals.items()]

    def get_flow_impact_of(self, impact_category, envi_flow) -> o.EnviFlowValue:
        self._check()
        f = self._factors.get(impact_category.id, {})
        key = self._key(envi_flow)
        return o.EnviFlowValue(
            amount=self.envi_totals.get(key, 0.0) * f.get(key[0], 0.0),
            envi_flow=envi_flow)

    # upstream trees

    def _upstream(self, path, per_unit, direct) -> List[o.UpstreamNode]:
        """Children of the last tech flow on the path; the root for []."""
        def node(pid, amount):
            return o.UpstreamNode(
                tech_flow=self._tech_flow(pid), required_amount=amount,
                result=per_unit(pid) * amount,
                direct_contribution=direct(pid) * amount)

        if not path:
            return [node(self.root.id, self.demand)]
        amount = self.demand
        pid = self.root.id
        for tf in path[1:]:
            nxt = tf.provider.id
            share = sum(s for p, s in self._children.get(pid, []) if p == nxt)
            amount *= share
            pid = nxt
        return [node(child, amount * share)
                for child, share in self._children.get(pid, [])]

    def get_upstream_impacts_of(self, impact_ref, path) -> List[o.UpstreamNode]:
        self._check()
        cid = impact_ref.id
        return self._upstream(
            path,
            lambda pid: self._per_unit_cache.get(pid, {}).get(cid, 0.0),
            lambda pid: self._direct_per_unit.get(pid, {}).get(cid, 0.0))

    def get_upstream_interventions_of(self, envi_flow, path) -> List[o.UpstreamNode]:
        self._check()
        key = self._key(envi_flow)
        return self._upstream(
            path,
            lambda pid: self._flows_per_unit.get(pid, {}).get(key, 0.0),
            lambda pid: self._flows_direct.get(pid, {}).get(key, 0.0))

    def get_upstream_costs_of(self, path) -> List[o.UpstreamNode]:
        self._check()
        return self._upstream(
            path, lambda pid: self._cost_per_unit.get(pid, 0.0),
            lambda pid: self._cost_direct.get(pid, 0.0))

    # costs

    def _with_costs(self) -> bool:
        return bool(self.setup is not None
                    and getattr(self.setup, "with_costs", False))

    def get_total_costs(self) -> o.CostValue:
        self._check()
        if not self._with_costs():
            return self._cost_value(0.0)
        return self._cost_value(
            self._cost_per_unit.get(self.root.id, 0.0) * self.demand)

    def get_cost_contributions(self) -> List[o.TechFlowValue]:
        self._check()
        if not self._with_costs():
            return []
        return [o.TechFlowValue(amount=self._cost_direct.get(pid, 0.0) * need,
                                tech_flow=self._tech_flow(pid))
                for pid, need in self.requirements.items()]

    def get_direct_costs_of(self, tech_flow) -> o.CostValue:
        self._check()
        return self._cost_value(
            self._cost_direct.get(tech_flow.provider.id, 0.0)
            * self._need(tech_flow))

    def get_cost_intensities_of(self, tech_flow) -> o.CostValue:
        self._check()
        return self._cost_value(
            self._cost_per_unit.get(tech_flow.provider.id, 0.0))

    def get_total_costs_of(self, tech_flow) -> o.CostValue:
        self._check()
        return self._cost_value(
            self._cost_per_unit.get(tech_flow.provider.id, 0.0)
            * self._need(tech_flow))

    # analysis groups

    def _group_names(self):
        """Group of every process named in an analysis group, and the
        name the reference process's group goes by (as openLCA does:
        its own group, or "Top")."""
        named = {}
        for g in self.system.analysis_groups or []:
            for ref in g.processes or []:
                named[ref.id] = g.name
        names = set(named.values())
        top = named.get(self.root.id)
        if top is None:
            top = next(t for t in ("Top", "Base", "Root", "_Top_")
                       if t not in names)
        return named, top

    def _grouped(self, direct) -> List[o.GroupValue]:
        """Each process's direct result goes to its own group, or to
        the group of whatever it supplies when it has none."""
        if not (self.system.analysis_groups or []):
            return []
        named, top = self._group_names()
        sums: Dict[str, float] = {}

        def walk(pid, amount, group, path):
            if pid in path:
                return
            group = named.get(pid, group)
            sums[group] = sums.get(group, 0.0) + direct(pid) * amount
            for child, share in self._children.get(pid, []):
                walk(child, amount * share, group, path + (pid,))

        walk(self.root.id, self.demand, top, ())
        return [o.GroupValue(group=g, amount=v) for g, v in sums.items()]

    def get_grouped_impact_results_of(self, impact) -> List[o.GroupValue]:
        self._check()
        cid = impact.id
        return self._grouped(
            lambda pid: self._direct_per_unit.get(pid, {}).get(cid, 0.0))

    def get_grouped_flow_results_of(self, envi_flow) -> List[o.GroupValue]:
        self._check()
        key = self._key(envi_flow)
        return self._grouped(
            lambda pid: self._flows_direct.get(pid, {}).get(key, 0.0))

    def get_grouped_cost_results(self) -> List[o.GroupValue]:
        self._check()
        if not self._with_costs():
            return []
        return self._grouped(lambda pid: self._cost_direct.get(pid, 0.0))

    # results by process tag (openLCA 2.7)

    def _tag_results(self, method: str, params) -> list:
        """Direct results of the processes carrying each tag."""
        if method.endswith("-impact"):
            cid = params["impactCategory"]["@id"]
            direct = lambda pid: self._direct_per_unit.get(pid, {}).get(cid, 0.0)
        elif method.endswith("-flow"):
            key = self._key(o.EnviFlow.from_dict(params["enviFlow"]))
            direct = lambda pid: self._flows_direct.get(pid, {}).get(key, 0.0)
        else:
            direct = lambda pid: self._cost_direct.get(pid, 0.0)
        sums: Dict[str, float] = {}
        for pid, need in self.requirements.items():
            proc = self.client.store["Process"].get(pid)
            for tag in (proc.tags or []) if proc else []:
                sums[tag] = sums.get(tag, 0.0) + direct(pid) * need
        return [{"tag": t, "amount": v} for t, v in sums.items()]

    # Sankey

    def get_sankey_graph(self, config) -> o.SankeyGraph:
        self._check()
        if config.impact_category is not None:
            cid = config.impact_category.id
            per_unit = lambda pid: self._per_unit_cache.get(pid, {}).get(cid, 0.0)
            direct = lambda pid: self._direct_per_unit.get(pid, {}).get(cid, 0.0)
        elif config.envi_flow is not None:
            key = self._key(config.envi_flow)
            per_unit = lambda pid: self._flows_per_unit.get(pid, {}).get(key, 0.0)
            direct = lambda pid: self._flows_direct.get(pid, {}).get(key, 0.0)
        else:
            return o.SankeyGraph(nodes=[], edges=[], root_index=0)
        total = per_unit(self.root.id) * self.demand
        min_share = config.min_share or 0.0
        max_nodes = config.max_nodes or 0
        order = list(self.requirements)
        keep = [pid for pid in order
                if pid == self.root.id or not total
                or abs(per_unit(pid) * self.requirements[pid] / total) >= min_share]
        if max_nodes:
            keep = keep[:max_nodes]
        index = {pid: i for i, pid in enumerate(keep)}
        nodes = [o.SankeyNode(
                    index=index[pid], tech_flow=self._tech_flow(pid),
                    direct_result=direct(pid) * self.requirements[pid],
                    total_result=per_unit(pid) * self.requirements[pid])
                 for pid in keep]
        edges = []
        for pid in keep:
            for child, share in self._children.get(pid, []):
                if child not in index:
                    continue
                flow = per_unit(child) * self.requirements[pid] * share
                edges.append(o.SankeyEdge(
                    node_index=index[pid], provider_index=index[child],
                    upstream_share=(flow / total) if total else 0.0))
        return o.SankeyGraph(nodes=nodes, edges=edges,
                             root_index=index[self.root.id])

    # Monte Carlo

    def _has_uncertainty(self) -> bool:
        for pid in self.requirements:
            proc = self.client.store["Process"].get(pid)
            for ex in (proc.exchanges or []) if proc else []:
                if ex.uncertainty is not None:
                    return True
            for p in (proc.parameters or []) if proc else []:
                if p.uncertainty is not None:
                    return True
        return any(p.uncertainty is not None
                   for p in self.client.store["Parameter"].values())

    def simulate_next(self):
        """One Monte Carlo run. Exchanges and parameters with an
        uncertainty distribution are drawn afresh; mc_jitter on the
        client spreads every total as a database full of uncertainty
        data would. With neither, every run gives the same numbers."""
        self._check()
        if not self.simulation and not self.client.lenient_simulation:
            return o.ResultState(id=self.uid, error="not a simulation result")
        self._run += 1
        spread = self.client.mc_jitter
        self._jitter = 1.0 + (self._rng.uniform(-spread, spread) if spread else 0.0)
        self._sampling = True
        try:
            self._compute()
        finally:
            self._sampling = False
        return o.ResultState(id=self.uid, is_ready=True)


class FakeClient:
    """In-memory olca_ipc.Client. See the module docstring."""

    TYPES = ("Process", "Flow", "FlowProperty", "UnitGroup", "ProductSystem",
             "ImpactMethod", "ImpactCategory", "Parameter", "Location",
             "DQSystem", "Actor", "Source", "Currency", "SocialIndicator",
             "Project", "Result", "Epd", "FlowMap")

    url = None   # the engine opens extra clients only when a URL is set

    def __init__(self):
        self.store: Dict[str, Dict[str, object]] = {t: {} for t in self.TYPES}
        self.direct_impacts: Dict[str, Dict[str, float]] = {}
        self.unit_by_id: Dict[str, o.Unit] = {}
        self.calls: List[tuple] = []          # every client call, for tests
        self.results: List[FakeResult] = []   # every calculation result
        self.setups: list = []                # the setup of each of them
        self.exports: list = []               # export/json-ld requests
        self.source_files: Dict[str, object] = {}
        self.shut_down = False
        self.mc_jitter = 0.0
        self.fail_next: Dict[str, Exception] = {}   # method name -> error
        # A calculate() result that is asked for Monte Carlo runs: the
        # real server refuses (simulate() is the call that makes a
        # simulation). False makes the fake as strict.
        self.lenient_simulation = False
        # The openLCA version the fake server pretends to be: decides
        # which IPC methods rpc_call understands.
        self.server_version = "2.6.2"

    # ── helpers ──────────────────────────────────────────────

    def _note(self, name, *args):
        self.calls.append((name,) + args)
        err = self.fail_next.pop(name, None)
        if err is not None:
            raise err

    def _table(self, model_type) -> Dict[str, object]:
        return self.store.setdefault(model_type.__name__, {})

    def _flow_name(self, flow_id) -> str:
        flow = self.store["Flow"].get(flow_id)
        return flow.name if flow else ""

    def _ref_unit_of_flow(self, flow) -> str:
        for f in (flow.flow_properties or []) if flow else []:
            if f.is_ref_flow_property and f.flow_property:
                fp = self.store["FlowProperty"].get(f.flow_property.id)
                ug = (self.store["UnitGroup"].get(fp.unit_group.id)
                      if fp and fp.unit_group else None)
                for u in (ug.units or []) if ug else []:
                    if u.is_ref_unit:
                        return u.name
        return ""

    def _location_code(self, loc_ref) -> str:
        if loc_ref is None:
            return ""
        loc = self.store["Location"].get(loc_ref.id)
        return (loc.code or loc.name) if loc else ""

    def _descriptor(self, entity) -> o.Ref:
        kind = type(entity).__name__
        ref = o.Ref(id=entity.id, name=entity.name,
                    category=getattr(entity, "category", None) or None,
                    ref_type=getattr(o.RefType, kind, None))
        if isinstance(entity, o.Process):
            ref.location = self._location_code(entity.location) or None
            ref.process_type = entity.process_type
            ref.flow_type = o.FlowType.PRODUCT_FLOW
        elif isinstance(entity, o.Flow):
            ref.flow_type = entity.flow_type
            ref.ref_unit = self._ref_unit_of_flow(entity) or None
        elif isinstance(entity, o.ImpactCategory):
            ref.ref_unit = entity.ref_unit
        return ref

    def _enrich(self, entity):
        """Fill in the names openLCA returns on nested references."""
        if isinstance(entity, o.Process):
            for ex in entity.exchanges or []:
                if ex.flow is not None:
                    flow = self.store["Flow"].get(ex.flow.id)
                    if flow is not None:
                        ex.flow.name = flow.name
                        ex.flow.flow_type = flow.flow_type
                if ex.default_provider is not None:
                    prov = self.store["Process"].get(ex.default_provider.id)
                    if prov is not None:
                        ex.default_provider.name = prov.name
                        ex.default_provider.location = (
                            self._location_code(prov.location) or None)
            if entity.location is not None:
                loc = self.store["Location"].get(entity.location.id)
                if loc is not None:
                    entity.location.name = loc.name
        elif isinstance(entity, o.ProductSystem):
            for link in entity.process_links or []:
                for ref, table in ((link.provider, "Process"),
                                   (link.process, "Process"),
                                   (link.flow, "Flow")):
                    if ref is not None and ref.id in self.store[table]:
                        ref.name = self.store[table][ref.id].name
        return entity

    # ── the Client API the engine uses ───────────────────────

    def get_descriptors(self, model_type) -> List[o.Ref]:
        self._note("get_descriptors", model_type.__name__)
        return [self._descriptor(e) for e in self._table(model_type).values()]

    def get_descriptor(self, model_type, uid: str = None, name: str = None):
        self._note("get_descriptor", model_type.__name__, uid or name)
        for e in self._table(model_type).values():
            if (uid and e.id == uid) or (name and e.name == name):
                return self._descriptor(e)
        return None

    def get(self, model_type, uid: str = None, name: str = None):
        self._note("get", model_type.__name__, uid or name)
        table = self._table(model_type)
        entity = table.get(uid) if uid else None
        if entity is None and name:
            entity = next((e for e in table.values() if e.name == name), None)
        if entity is None:
            return None
        return self._enrich(copy.deepcopy(entity))

    def get_all(self, model_type):
        self._note("get_all", model_type.__name__)
        return [self._enrich(copy.deepcopy(e))
                for e in self._table(model_type).values()]

    def find(self, model_type, name: str):
        self._note("find", model_type.__name__, name)
        for e in self._table(model_type).values():
            if e.name == name:
                return self._descriptor(e)
        return None

    def put(self, entity) -> o.Ref:
        self._note("put", type(entity).__name__, getattr(entity, "name", ""))
        if not getattr(entity, "id", None):
            entity.id = str(uuid.uuid4())
        stored = copy.deepcopy(entity)
        if isinstance(stored, o.UnitGroup):
            for u in stored.units or []:
                self.unit_by_id[u.id] = u
        self.store.setdefault(type(stored).__name__, {})[stored.id] = stored
        return self._descriptor(stored)

    def delete(self, entity):
        self._note("delete", type(entity).__name__, getattr(entity, "name", ""))
        kind = type(entity).__name__
        if isinstance(entity, o.Ref) and entity.ref_type is not None:
            kind = entity.ref_type.name
        self.store.get(kind, {}).pop(entity.id, None)
        return o.Ref(id=entity.id, name=getattr(entity, "name", None))

    def _system_process_ids(self, system) -> List[str]:
        ids = []
        if system.ref_process is not None:
            ids.append(system.ref_process.id)
        for ref in system.processes or []:
            if ref.id not in ids:
                ids.append(ref.id)
        for link in system.process_links or []:
            for ref in (link.provider, link.process):
                if ref is not None and ref.id not in ids:
                    ids.append(ref.id)
        return ids

    def get_parameters(self, model_type, uid: str):
        """Redefinable parameters of a product system: global input
        parameters (no context) and the input parameters of every
        process in the system (context is the process)."""
        self._note("get_parameters", model_type.__name__, uid)
        if model_type is not o.ProductSystem:
            entity = self._table(model_type).get(uid)
            return list(getattr(entity, "parameters", None) or [])
        system = self.store["ProductSystem"].get(uid)
        if system is None:
            return []
        out = []
        for p in self.store["Parameter"].values():
            if p.is_input_parameter:
                out.append(o.ParameterRedef(name=p.name, value=p.value, context=None))
        for pid in self._system_process_ids(system):
            proc = self.store["Process"].get(pid)
            for p in (proc.parameters or []) if proc else []:
                if p.is_input_parameter:
                    out.append(o.ParameterRedef(
                        name=p.name, value=p.value,
                        context=o.Ref(id=proc.id, name=proc.name,
                                      ref_type=o.RefType.Process)))
        return out

    def _providers_of_flow(self, flow_id) -> List[o.Process]:
        out = []
        for proc in self.store["Process"].values():
            for ex in proc.exchanges or []:
                if (ex.is_quantitative_reference and ex.flow
                        and ex.flow.id == flow_id):
                    out.append(proc)
        return out

    def get_providers(self, flow=None) -> List[o.TechFlow]:
        self._note("get_providers", getattr(flow, "id", None))
        out = []
        procs = (self._providers_of_flow(flow.id) if flow is not None
                 else list(self.store["Process"].values()))
        for proc in procs:
            qref = next((ex for ex in proc.exchanges or []
                         if ex.is_quantitative_reference and ex.flow), None)
            if qref is None:
                continue
            out.append(o.TechFlow(
                provider=o.Ref(id=proc.id, name=proc.name,
                               ref_type=o.RefType.Process),
                flow=o.Ref(id=qref.flow.id, name=self._flow_name(qref.flow.id),
                           ref_type=o.RefType.Flow)))
        return out

    def create_product_system(self, process, config=None) -> Optional[o.Ref]:
        """Build a product system by following providers from a process.
        An exchange is linked to its default provider if it has one;
        otherwise, unless linking is ONLY_DEFAULTS, to the first process
        that produces the flow."""
        self._note("create_product_system", process.id)
        root = self.store["Process"].get(process.id)
        if root is None:
            raise RuntimeError(f"process {process.id} not found")
        only_defaults = (config is not None and config.provider_linking
                         == o.ProviderLinking.ONLY_DEFAULTS)
        links, seen, queue = [], [], [root.id]
        while queue:
            pid = queue.pop(0)
            if pid in seen:
                continue
            seen.append(pid)
            proc = self.store["Process"].get(pid)
            if proc is None:
                continue
            for ex in proc.exchanges or []:
                if ex.is_quantitative_reference or ex.flow is None:
                    continue
                flow = self.store["Flow"].get(ex.flow.id)
                if flow is None or flow.flow_type == o.FlowType.ELEMENTARY_FLOW:
                    continue
                is_link = ((ex.is_input and flow.flow_type == o.FlowType.PRODUCT_FLOW)
                           or (not ex.is_input
                               and flow.flow_type == o.FlowType.WASTE_FLOW))
                if not is_link:
                    continue
                provider_id = ex.default_provider.id if ex.default_provider else None
                if provider_id is None and not only_defaults:
                    candidates = [p for p in self._providers_of_flow(flow.id)
                                  if p.id != pid]
                    provider_id = candidates[0].id if candidates else None
                if provider_id is None or provider_id not in self.store["Process"]:
                    continue
                links.append(o.ProcessLink(
                    provider=o.Ref(id=provider_id, ref_type=o.RefType.Process),
                    flow=o.Ref(id=flow.id, ref_type=o.RefType.Flow),
                    process=o.Ref(id=pid, ref_type=o.RefType.Process),
                    exchange=o.ExchangeRef(internal_id=ex.internal_id)))
                queue.append(provider_id)
        system = o.ProductSystem(
            id=str(uuid.uuid4()), name=root.name, category=root.category,
            ref_process=o.Ref(id=root.id, name=root.name,
                              ref_type=o.RefType.Process),
            processes=[o.Ref(id=pid, ref_type=o.RefType.Process) for pid in seen],
            process_links=links, target_amount=1.0)
        self.store["ProductSystem"][system.id] = system
        return self._descriptor(system)

    def _redefs_of(self, setup, system):
        """As the server does: without redefinitions in the setup, the
        baseline parameter set of the system applies."""
        if setup.parameters is not None:
            return setup.parameters
        for ps in system.parameter_sets or []:
            if ps.is_baseline:
                return ps.parameters
        return None

    def _new_result(self, setup, simulation: bool) -> FakeResult:
        system = self.store["ProductSystem"].get(setup.target.id)
        if system is None:
            raise RuntimeError(f"product system {setup.target.id} not found")
        result = FakeResult(self, system, setup.impact_method,
                            self._redefs_of(setup, system), setup=setup,
                            simulation=simulation)
        self.results.append(result)
        self.setups.append(setup)
        return result

    def calculate(self, setup) -> FakeResult:
        self._note("calculate", getattr(setup.target, "id", None))
        return self._new_result(setup, simulation=False)

    def simulate(self, setup) -> FakeResult:
        self._note("simulate", getattr(setup.target, "id", None))
        return self._new_result(setup, simulation=True)

    # ── raw JSON-RPC, for the methods the client does not wrap ──

    SINCE = {"data/get/usage": "2.7", "result/tag-results-of-impact": "2.7",
             "result/tag-results-of-flow": "2.7",
             "result/tag-results-of-costs": "2.7",
             "data/put/source-file": "2.6.2"}

    @staticmethod
    def _version_tuple(text: str) -> tuple:
        return tuple(int(p) for p in text.split("."))

    def _result_by_uid(self, uid):
        return next((r for r in self.results
                     if r.uid == uid and not r.disposed), None)

    def rpc_call(self, method: str, params=None):
        """(result, error), as olca_ipc.Client.rpc_call gives them."""
        self._note("rpc_call", method)
        since = self.SINCE.get(method)
        if since and (self._version_tuple(self.server_version)
                      < self._version_tuple(since)):
            return None, f"-32601: Does not understand: {method}"
        if method == "runtime/shutdown":
            self.shut_down = True
            return "ok", None
        if method == "export/json-ld":
            if not params or not params.get("path"):
                return None, "400: No `path` given"
            self.exports.append(params)
            return "ok", None
        if method == "data/get/usage":
            if not params:
                return None, "-32602: Invalid parameters"
            return [r.to_dict() for r in self._usage_of(
                params.get("@type"), params.get("@id"))], None
        if method.startswith("result/"):
            if not params or not params.get("@id"):
                return None, "-32602: Invalid parameters"
            result = self._result_by_uid(params["@id"])
            if result is None:
                return None, "404: no such result"
            result._check()
            tf = (o.TechFlow.from_dict(params["techFlow"])
                  if params.get("techFlow") else None)
            if method == "result/impact-intensities-of":
                return [v.to_dict() for v in result._intensities(tf)], None
            if method == "result/totality-factors":
                return [v.to_dict() for v in result.get_total_requirements()], None
            if method == "result/totality-factor-of":
                return result.get_total_requirements_of(tf).to_dict(), None
            if method.startswith("result/tag-results-of-"):
                return result._tag_results(method, params), None
        return None, f"-32601: Does not understand: {method}"

    def _usage_of(self, type_name, uid) -> List[o.Ref]:
        """Where an entity is used (openLCA 2.7's data/get/usage)."""
        out = []
        if type_name == "Flow":
            for proc in self.store["Process"].values():
                if any(ex.flow and ex.flow.id == uid
                       for ex in proc.exchanges or []):
                    out.append(self._descriptor(proc))
            for cat in self.store["ImpactCategory"].values():
                if any(f.flow and f.flow.id == uid
                       for f in cat.impact_factors or []):
                    out.append(self._descriptor(cat))
        elif type_name == "Process":
            for system in self.store["ProductSystem"].values():
                if uid in self._system_process_ids(system):
                    out.append(self._descriptor(system))
        return out

    def put_source_file(self, source, file_data) -> bool:
        self._note("put_source_file", getattr(source, "id", None))
        if (self._version_tuple(self.server_version)
                < self._version_tuple(self.SINCE["data/put/source-file"])):
            return False
        self.source_files[source.id] = file_data
        stored = self.store["Source"].get(source.id)
        if stored is not None:
            stored.external_file = file_data.name
        return True

    # ── convenience for tests ────────────────────────────────

    def undisposed(self) -> int:
        return sum(1 for r in self.results if not r.disposed)

    def by_name(self, model_type, name: str):
        return [e for e in self._table(model_type).values() if e.name == name]

    def add_location(self, code: str, name: str) -> o.Ref:
        loc = o.Location(id=_uid("loc", code), code=code, name=name)
        self.store["Location"][loc.id] = loc
        return o.Ref(id=loc.id, name=name, ref_type=o.RefType.Location)

    def add_unit_group(self, name: str, units: Dict[str, float], ref: str) -> o.UnitGroup:
        ug = o.UnitGroup(id=_uid("ug", name), name=name, units=[
            o.Unit(id=_uid("unit", u), name=u, conversion_factor=f,
                   is_ref_unit=(u == ref)) for u, f in units.items()])
        self.put(ug)
        return ug

    def add_flow_property(self, name: str, unit_group: o.UnitGroup) -> o.FlowProperty:
        fp = o.FlowProperty(
            id=_uid("fp", name), name=name,
            unit_group=o.Ref(id=unit_group.id, name=unit_group.name,
                             ref_type=o.RefType.UnitGroup))
        self.put(fp)
        return fp

    def add_flow(self, name: str, prop: str, flow_type=o.FlowType.PRODUCT_FLOW,
                 category: str = "") -> o.Flow:
        fp = next(p for p in self.store["FlowProperty"].values() if p.name == prop)
        flow = o.Flow(
            id=_uid("flow", name, category), name=name, category=category,
            flow_type=flow_type,
            flow_properties=[o.FlowPropertyFactor(
                flow_property=o.Ref(id=fp.id, name=fp.name,
                                    ref_type=o.RefType.FlowProperty),
                conversion_factor=1.0, is_ref_flow_property=True)])
        self.put(flow)
        return flow

    def _unit_ref(self, name: str) -> o.Ref:
        for uid, u in self.unit_by_id.items():
            if u.name == name:
                return o.Ref(id=uid, name=name, ref_type=o.RefType.Unit)
        raise KeyError(name)

    def add_background_process(self, name: str, flow: o.Flow, unit: str,
                               location: str = "", category: str = "",
                               impacts: Optional[Dict[str, float]] = None,
                               waste_treatment: bool = False) -> o.Process:
        """A background dataset: one reference exchange and canned
        direct impacts per unit of it."""
        loc = next((l for l in self.store["Location"].values()
                    if l.code == location), None)
        qref = o.Exchange(
            internal_id=1, amount=1.0, is_input=waste_treatment,
            is_quantitative_reference=True, is_avoided_product=False,
            flow=o.Ref(id=flow.id, name=flow.name, ref_type=o.RefType.Flow),
            unit=self._unit_ref(unit))
        proc = o.Process(
            id=_uid("proc", name, location), name=name, category=category,
            process_type=o.ProcessType.UNIT_PROCESS, exchanges=[qref],
            last_internal_id=1,
            location=(o.Ref(id=loc.id, name=loc.name,
                            ref_type=o.RefType.Location) if loc else None))
        self.put(proc)
        self.direct_impacts[proc.id] = dict(impacts or {})
        return proc

    def add_method(self, name: str, categories: Dict[str, str],
                   factors: Optional[Dict[str, Dict[str, float]]] = None) -> o.ImpactMethod:
        """categories: {category name: unit}. factors: {category name:
        {flow id: characterisation factor}} for elementary flows."""
        refs = []
        for cat_name, unit in categories.items():
            cat = o.ImpactCategory(
                id=_uid("cat", name, cat_name), name=cat_name, ref_unit=unit,
                category=name,
                impact_factors=[
                    o.ImpactFactor(flow=o.Ref(id=fid, ref_type=o.RefType.Flow),
                                   value=v)
                    for fid, v in ((factors or {}).get(cat_name) or {}).items()])
            self.store["ImpactCategory"][cat.id] = cat
            refs.append(o.Ref(id=cat.id, name=cat_name, ref_unit=unit,
                              ref_type=o.RefType.ImpactCategory))
        method = o.ImpactMethod(id=_uid("method", name), name=name,
                                impact_categories=refs)
        self.store["ImpactMethod"][method.id] = method
        return method


def nothing_left_open(client: "FakeClient"):
    """Every result is disposed: close what the engines on this client
    still hold open (as a Session does on close and Python does on
    exit), then nothing may be left undisposed. Test fixtures call this
    when a test ends."""
    from olcabasic.engine import results
    for engine in list(results._ENGINES):
        if engine.client is client:
            engine.close_all_results()
    assert client.undisposed() == 0, (
        f"{client.undisposed()} calculation result(s) were never disposed")


# ── a seeded, synthetic, ecoinvent-shaped database ───────────

BACKGROUND_CATEGORY = "D:Test supply/35:Test supply/351:Test generation"
ELECTRICITY = ("market for test electricity, medium voltage | "
               "test electricity, medium voltage | Cutoff, U")
STEEL = "market for test steel, low-alloyed | test steel, low-alloyed | Cutoff, U"
WATER = "market for test water | test water | Cutoff, U"
PLASTIC = "market for test polymer, granulate | test polymer, granulate | Cutoff, U"
TRANSPORT = ("market for test transport, freight, lorry | "
             "test transport, freight, lorry | Cutoff, U")
LANDFILL = ("treatment of test waste, sanitary landfill | "
            "test waste | Cutoff, U")

EF_CATEGORIES = {
    "Acidification": "mol H+-Eq",
    "Climate change": "kg CO2-Eq",
    "Climate change: biogenic": "kg CO2-Eq",
    "Climate change: fossil": "kg CO2-Eq",
    "Eutrophication: freshwater": "kg P-Eq",
    "Water use": "m3 world Eq deprived",
}
IPCC_CATEGORIES = {
    "Climate change: fossil - Global warming potential (GWP100)": "kg CO2-Eq",
    "Climate change: biogenic - Global warming potential (GWP100)": "kg CO2-Eq",
    "Climate change: total - Global warming potential (GWP100)": "kg CO2-Eq",
}


def _impacts(gwp: float, biogenic: float = 0.0, acid: float = 0.0,
             eutro: float = 0.0, water: float = 0.0) -> Dict[str, float]:
    return {
        "Acidification": acid,
        "Climate change": gwp + biogenic,
        "Climate change: biogenic": biogenic,
        "Climate change: fossil": gwp,
        "Eutrophication: freshwater": eutro,
        "Water use": water,
        "Climate change: fossil - Global warming potential (GWP100)": gwp,
        "Climate change: biogenic - Global warming potential (GWP100)": biogenic,
        "Climate change: total - Global warming potential (GWP100)": gwp + biogenic,
        **_epd_impacts(gwp, biogenic, acid, eutro, water),
    }


# A synthetic EN 15804+A2 indicator set: the right number of categories
# for the EPD workflow's method check, with made-up names (only the
# climate ones mean anything; the rest are numbered).
EPD_METHOD = "EN15804+A2 (EF 3.1)"
EPD_SHORT_METHOD = "Environment | EN15804+A2 (EF v3.1)"
EPD_GWP = "Test climate change, GWP-GHG"
EPD_CATEGORIES = {
    "Test climate change, total": "kg CO2 eq.",
    "Test climate change, fossil": "kg CO2 eq.",
    "Test climate change, biogenic": "kg CO2 eq.",
    EPD_GWP: "kg CO2 eq.",
    **{f"Test indicator {n:02d}": "test unit" for n in range(5, 39)},
}
EPD_SHORT_CATEGORIES = dict(list(EPD_CATEGORIES.items())[:20])


def _epd_impacts(gwp, biogenic, acid, eutro, water) -> Dict[str, float]:
    out = {"Test climate change, total": gwp + biogenic,
           "Test climate change, fossil": gwp,
           "Test climate change, biogenic": biogenic,
           EPD_GWP: gwp}
    for n in range(5, 39):
        out[f"Test indicator {n:02d}"] = (acid, eutro, water)[n % 3] * n
    return out


def add_epd_methods(client: "FakeClient") -> "FakeClient":
    """Add the synthetic EN 15804+A2 method (38 categories) and its
    shorter namesake (20), as an LCIA pack would."""
    client.add_method(EPD_METHOD, EPD_CATEGORIES)
    client.add_method(EPD_SHORT_METHOD, EPD_SHORT_CATEGORIES)
    return client


def seed_ecoinvent_like(client: Optional[FakeClient] = None) -> FakeClient:
    """A small synthetic database shaped like ecoinvent in openLCA:
    ecoinvent flow property names, processes that share a name and
    differ by location, elementary flows in sub-compartments, and
    impact methods with near-identical names."""
    c = client or FakeClient()

    mass = c.add_unit_group("Units of mass", {"kg": 1.0, "g": 0.001, "t": 1000.0}, "kg")
    energy = c.add_unit_group("Units of energy", {"MJ": 1.0, "kWh": 3.6, "GJ": 1000.0}, "MJ")
    volume = c.add_unit_group("Units of volume", {"m3": 1.0, "l": 0.001}, "m3")
    masslen = c.add_unit_group("Units of mass*length", {"t*km": 1.0, "kg*km": 0.001}, "t*km")
    time_ = c.add_unit_group("Units of time", {"h": 1.0, "d": 24.0, "a": 8760.0}, "h")
    length = c.add_unit_group("Units of length", {"m": 1.0, "km": 1000.0}, "m")
    area = c.add_unit_group("Units of area", {"m2": 1.0, "ha": 10000.0}, "m2")
    items = c.add_unit_group("Units of amount", {"Item(s)": 1.0}, "Item(s)")
    for name, ug in (("Mass", mass), ("Energy", energy), ("Volume", volume),
                     ("Mass transport", masslen), ("Time", time_),
                     ("Length", length), ("Area", area),
                     ("Number of items", items)):
        c.add_flow_property(name, ug)

    for code, name in (("GB", "United Kingdom"), ("DE", "Germany"),
                       ("RoW", "Rest-of-World"), ("GLO", "Global"),
                       ("RER", "Europe"), ("US-WECC", "United States, WECC")):
        c.add_location(code, name)

    elec = c.add_flow("test electricity, medium voltage", "Energy",
                      category=BACKGROUND_CATEGORY)
    steel = c.add_flow("test steel, low-alloyed", "Mass", category="C:Test manufacturing")
    water = c.add_flow("test water", "Mass", category="E:Test water supply")
    plastic = c.add_flow("test polymer, granulate", "Mass", category="C:Test manufacturing")
    transport = c.add_flow("test transport, freight, lorry", "Mass transport",
                           category="H:Test transport")
    waste = c.add_flow("test waste", "Mass", o.FlowType.WASTE_FLOW,
                       category="E:Test water supply")

    for loc, gwp in (("GB", 0.25), ("DE", 0.40), ("RoW", 0.70)):
        c.add_background_process(ELECTRICITY, elec, "kWh", loc, BACKGROUND_CATEGORY,
                                 _impacts(gwp, 0.001, 0.0004, 0.00002, 0.01))
    c.add_background_process(STEEL, steel, "kg", "GLO", "C:Test manufacturing",
                             _impacts(2.0, 0.01, 0.008, 0.0009, 0.05))
    for loc, gwp in (("RER", 0.0003), ("RoW", 0.0006)):
        c.add_background_process(WATER, water, "kg", loc, "E:Test water supply",
                                 _impacts(gwp, 0.0, 0.000002, 0.0000002, 0.001))
    for loc, gwp in (("RER", 1.9), ("RoW", 2.3)):
        c.add_background_process(PLASTIC, plastic, "kg", loc, "C:Test manufacturing",
                                 _impacts(gwp, 0.02, 0.006, 0.0004, 0.03))
    c.add_background_process(TRANSPORT, transport, "t*km", "RER", "H:Test transport",
                             _impacts(0.12, 0.0, 0.0005, 0.00001, 0.0002))
    c.add_background_process(LANDFILL, waste, "kg", "RoW", "E:Test water supply",
                             _impacts(0.05, 0.3, 0.0001, 0.002, 0.0001),
                             waste_treatment=True)

    air = "Elementary flows/Emission to air"
    co2_u = c.add_flow("Carbon dioxide, fossil", "Mass", o.FlowType.ELEMENTARY_FLOW,
                       category=air + "/unspecified")
    co2_c = c.add_flow("Carbon dioxide, fossil", "Mass", o.FlowType.ELEMENTARY_FLOW,
                       category=air + "/urban air close to ground")
    ch4 = c.add_flow("Methane, fossil", "Mass", o.FlowType.ELEMENTARY_FLOW,
                     category=air + "/unspecified")
    c.add_flow("Phosphate", "Mass", o.FlowType.ELEMENTARY_FLOW,
               category="Elementary flows/Emission to water/surface water")
    c.add_flow("Water, river", "Volume", o.FlowType.ELEMENTARY_FLOW,
               category="Elementary flows/Resource/in water")
    c.add_flow("Zinc", "Mass", o.FlowType.ELEMENTARY_FLOW,
               category="Elementary flows/Emission to soil/unspecified")

    cf = {co2_u.id: 1.0, co2_c.id: 1.0, ch4.id: 29.8}
    ef_factors = {"Climate change": cf, "Climate change: fossil": cf}
    for name in ("EF v3.0", "EF v3.0 no LT", "EF v3.1", "EF v3.1 no LT"):
        c.add_method(name, EF_CATEGORIES, ef_factors)
    ipcc = {"Climate change: fossil - Global warming potential (GWP100)": cf,
            "Climate change: total - Global warming potential (GWP100)": cf}
    for name in ("IPCC 2021", "IPCC 2021 no LT", "IPCC 2013"):
        c.add_method(name, IPCC_CATEGORIES, ipcc)

    for name, n in (("Test Pedigree Matrix", 5), ("Test Process Quality System", 4)):
        dq = o.DQSystem(id=_uid("dq", name), name=name, indicators=[
            o.DQIndicator(name=f"Indicator {i}", position=i,
                          scores=[o.DQScore(position=s, label=str(s))
                                  for s in range(1, 6)])
            for i in range(1, n + 1)])
        c.store["DQSystem"][dq.id] = dq

    c.calls.clear()
    return c
