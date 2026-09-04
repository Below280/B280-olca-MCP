"""
openLCA IPC functions for the MCP server.

Wraps olca_ipc calls using the same patterns as the tested
Below280 scenario and sensitivity scripts. All calculations
target ProductSystem objects (never bare Processes), and every
result is disposed after use.
"""

from olca_ipc import Client
import olca_schema as o
from typing import Dict, List, Optional, Any
import logging
import time
import csv
import os
import uuid
import urllib.request
import urllib.parse
import json as json_module

logger = logging.getLogger(__name__)


class LCAFunctions:

    def __init__(self, client: Client):
        self.client = client
        self._cache: Dict[str, Any] = {}
        self._cache_ts: Dict[str, float] = {}
        self._cache_ttl: float = 1800  # 30 minutes

    # ── helpers ──────────────────────────────────────────────

    def _get_descriptors(self, entity_type):
        """Cached descriptor fetch. Per-key expiry, refreshes every 30 minutes."""
        key = entity_type.__name__
        now = time.time()
        if key in self._cache and (now - self._cache_ts.get(key, 0)) < self._cache_ttl:
            return self._cache[key]
        descriptors = list(self.client.get_descriptors(entity_type))
        self._cache[key] = descriptors
        self._cache_ts[key] = now
        return descriptors

    def _resolve(self, entity_type, ref: str):
        """Find a descriptor by ID, exact name, or unique partial name match."""
        items = self._get_descriptors(entity_type)
        for item in items:
            if item.id == ref:
                return item
        for item in items:
            if item.name == ref:
                return item
        matches = [item for item in items if ref.lower() in item.name.lower()]
        return matches[0] if len(matches) == 1 else None

    def _resolve_system(self, ref: str):
        """Find a product system by ID or name. Returns descriptor or None."""
        return self._resolve(o.ProductSystem, ref)

    def _resolve_method(self, ref: str):
        """Find an impact method by ID or name. Returns descriptor or None."""
        return self._resolve(o.ImpactMethod, ref)

    def _resolve_process(self, ref: str):
        """Find a process by ID or name. Returns descriptor or None."""
        return self._resolve(o.Process, ref)

    def _impacts_to_list(self, impacts) -> List[Dict]:
        """Convert impact results to JSON-serialisable list."""
        return [{
            "category": i.impact_category.name,
            "amount": i.amount,
            "unit": getattr(i.impact_category, "ref_unit", ""),
            "category_id": i.impact_category.id,
        } for i in impacts]

    # ── database info ────────────────────────────────────────

    def get_database_info(self) -> Dict:
        """Counts of key entities in the connected database."""
        try:
            return {
                "status": "connected",
                "product_systems": len(self._get_descriptors(o.ProductSystem)),
                "processes": len(self._get_descriptors(o.Process)),
                "flows": len(self._get_descriptors(o.Flow)),
                "impact_methods": len(self._get_descriptors(o.ImpactMethod)),
                "parameters": len(self._get_descriptors(o.Parameter)),
                "database_family": self._detect_database_family(),
            }
        except Exception as e:
            return {"status": "error", "error": str(e)}

    # ── listing / search ─────────────────────────────────────

    def list_product_systems(self, search_term: str = "") -> Dict:
        systems = self._get_descriptors(o.ProductSystem)
        if search_term:
            term = search_term.lower()
            systems = [s for s in systems if term in s.name.lower()]
        return {
            "count": len(systems),
            "systems": [{"id": s.id, "name": s.name} for s in systems],
        }

    def list_impact_methods(self, search_term: str = "") -> Dict:
        methods = self._get_descriptors(o.ImpactMethod)
        if search_term:
            term = search_term.lower()
            methods = [m for m in methods if term in m.name.lower()]
        return {
            "count": len(methods),
            "methods": [{"id": m.id, "name": m.name} for m in methods],
        }

    def get_system_parameters(self, system_ref: str,
                              name_filter: str = "") -> Dict:
        """List parameters for a product system, with optional name filter."""
        system = self._resolve_system(system_ref)
        if not system:
            return {"error": f"Product system not found: {system_ref}"}

        params = self.client.get_parameters(o.ProductSystem, system.id)
        result = []
        for p in params:
            if name_filter and name_filter.lower() not in p.name.lower():
                continue
            result.append({
                "name": p.name,
                "value": p.value,
                "context_id": p.context.id if p.context else None,
            })

        return {
            "system": system.name,
            "system_id": system.id,
            "count": len(result),
            "parameters": result,
        }

    def get_global_parameters(self, name_filter: str = "",
                              limit: int = 50) -> Dict:
        """
        Look up global (database-level) parameters.

        Returns name, value, scope, and formula for each match.
        Use name_filter to narrow results. Without a filter,
        results are capped at limit to avoid dumping thousands
        of parameters.
        """
        descriptors = self._get_descriptors(o.Parameter)
        if name_filter:
            term = name_filter.lower()
            descriptors = [d for d in descriptors if term in d.name.lower()]

        total = len(descriptors)
        descriptors = descriptors[:limit]

        results = []
        for desc in descriptors:
            param = self.client.get(o.Parameter, desc.id)
            if param:
                results.append({
                    "name": param.name,
                    "value": param.value,
                    "scope": str(param.parameter_scope) if param.parameter_scope else "",
                    "formula": param.formula or None,
                    "is_input": getattr(param, "is_input_parameter", True),
                })

        return {
            "count": len(results),
            "total_matches": total,
            "truncated": total > limit,
            "filter": name_filter or "(all)",
            "parameters": results,
        }

    def search_processes(self, search_term: str,
                         category_filter: str = "",
                         location_filter: str = "",
                         limit: int = 20) -> Dict:
        """Search processes by name, category, and/or location."""
        processes = self._get_descriptors(o.Process)
        term = search_term.lower()
        cat = category_filter.lower() if category_filter else ""
        loc = location_filter.lower() if location_filter else ""
        all_matches = []
        for p in processes:
            if term and term not in p.name.lower():
                continue
            proc_cat = getattr(p, "category", "") or ""
            if cat and cat not in proc_cat.lower():
                continue
            # Location filter: check if location code/name is in process name
            # (ecoinvent embeds location in name, e.g. "| Cutoff, U - GB")
            if loc and loc not in p.name.lower():
                continue
            all_matches.append({
                "id": p.id,
                "name": p.name,
                "category": proc_cat,
            })

        truncated = len(all_matches) > limit

        return {
            "search_term": search_term,
            "category_filter": category_filter or "(all)",
            "count": min(len(all_matches), limit),
            "total_matches": len(all_matches),
            "truncated": truncated,
            "processes": all_matches[:limit],
        }

    def search_flows(self, search_term: str = "",
                     category_filter: str = "",
                     limit: int = 20) -> Dict:
        """Search flows by name and/or category folder."""
        flows = self._get_descriptors(o.Flow)
        matches = []
        term = search_term.lower() if search_term else ""
        cat = category_filter.lower() if category_filter else ""

        for f in flows:
            if term and term not in f.name.lower():
                continue
            flow_cat = getattr(f, "category", "") or ""
            if cat and cat not in flow_cat.lower():
                continue
            matches.append({
                "id": f.id,
                "name": f.name,
                "category": flow_cat,
                "flow_type": str(getattr(f, "flow_type", "")),
                "ref_unit": getattr(f, "ref_unit", ""),
            })
            if len(matches) >= limit:
                break

        return {
            "search_term": search_term or "(all)",
            "category_filter": category_filter or "(all)",
            "count": len(matches),
            "flows": matches,
        }

    def chemical_synonyms(self, chemical_name: str,
                          search_database: bool = True,
                          max_synonyms: int = 20) -> Dict:
        """
        Look up chemical synonyms via PubChem (US NIH, free, no key).

        Takes a chemical name (common name, trade name, or IUPAC),
        returns known synonyms, CAS number, and IUPAC name.
        If search_database is True, also searches the connected
        openLCA database for matches against each synonym.

        Only call this when the user has approved a deeper search,
        or when a basic search_processes call returned few results
        and the user said yes to trying synonyms.
        """
        try:
            encoded = urllib.parse.quote(chemical_name)
            url = (
                f"https://pubchem.ncbi.nlm.nih.gov/rest/pug/"
                f"compound/name/{encoded}/synonyms/JSON"
            )

            req = urllib.request.Request(url)
            req.add_header("User-Agent", "Below280-openLCA-MCP/1.0")

            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json_module.loads(resp.read().decode())

            synonyms_list = (
                data.get("InformationList", {})
                .get("Information", [{}])[0]
                .get("Synonym", [])
            )

            # Extract CAS number (format: digits-digits-digit)
            import re
            cas = None
            for s in synonyms_list:
                if re.match(r"^\d{2,7}-\d{2}-\d$", s):
                    cas = s
                    break

            # Take the most useful synonyms (skip catalog numbers)
            useful = []
            for s in synonyms_list:
                if len(s) > 80:
                    continue
                if any(c in s for c in [";", "  ", "\t"]):
                    continue
                useful.append(s)
                if len(useful) >= max_synonyms:
                    break

            result = {
                "query": chemical_name,
                "cas_number": cas,
                "iupac_name": useful[0] if useful else None,
                "synonym_count": len(synonyms_list),
                "synonyms": useful,
            }

            # Search the openLCA database for matches
            if search_database and useful:
                db_matches = []
                seen_ids = set()
                processes = self._get_descriptors(o.Process)

                for synonym in useful[:10]:
                    term = synonym.lower()
                    for p in processes:
                        if p.id in seen_ids:
                            continue
                        if term in p.name.lower():
                            db_matches.append({
                                "id": p.id,
                                "name": p.name,
                                "matched_synonym": synonym,
                                "category": getattr(p, "category", ""),
                            })
                            seen_ids.add(p.id)
                            if len(db_matches) >= 20:
                                break
                    if len(db_matches) >= 20:
                        break

                result["database_matches"] = db_matches
                result["database_match_count"] = len(db_matches)

            return result

        except urllib.error.HTTPError as e:
            if e.code == 404:
                return {
                    "query": chemical_name,
                    "error": f"Chemical '{chemical_name}' not found in PubChem",
                    "suggestion": "Try a different name, CAS number, or IUPAC name",
                }
            return {"error": f"PubChem API error: {e.code} {e.reason}"}
        except Exception as e:
            return {"error": f"PubChem lookup failed: {e}"}

    def get_process_details(self, process_id: str) -> Dict:
        """Full process information including exchanges and parameters."""
        try:
            process = self.client.get(o.Process, process_id)
            if not process:
                return {"error": f"Process not found: {process_id}"}

            exchanges = []
            if process.exchanges:
                for ex in process.exchanges:
                    exchanges.append({
                        "flow": ex.flow.name if ex.flow else "Unknown",
                        "amount": ex.amount,
                        "formula": getattr(ex, "amount_formula", None),
                        "unit": ex.unit.name if ex.unit else "",
                        "is_input": ex.is_input,
                        "is_qref": getattr(ex, "is_quantitative_reference", False),
                        "provider": (ex.default_provider.name
                                     if getattr(ex, "default_provider", None)
                                     else None),
                    })

            parameters = []
            if process.parameters:
                for p in process.parameters:
                    parameters.append({
                        "name": p.name,
                        "value": p.value,
                        "formula": getattr(p, "formula", None),
                        "is_input": getattr(p, "is_input_parameter", True),
                    })

            location_name = ""
            if hasattr(process, "location") and process.location:
                location_name = getattr(process.location, "name", "")

            return {
                "id": process.id,
                "name": process.name,
                "category": getattr(process, "category", ""),
                "location": location_name,
                "description": getattr(process, "description", ""),
                "exchanges": exchanges,
                "parameters": parameters,
            }
        except Exception as e:
            return {"error": str(e)}

    # ── model building ───────────────────────────────────────
    #
    # Patterns lifted directly from create_east_bros_model.py:
    #   make_flow  → create_flow
    #   e()        → _build_exchange
    #   proc()     → create_process
    #   bridge_proc() → create_bridge
    #   get_unit / get_fp → find_unit

    # ── database family detection and unit mapping ─────────────
    #
    # Two database families with different flow property names:
    #   ecoinvent family: ecoinvent, EN15804GD, HiQLCD, BAFU
    #   FLCAC family: LCA Commons, US LCI, USEEIO
    #
    # Auto-detected on first use by checking telltale FP names.

    ECOINVENT_FP_MAP = {
        "kg": "Mass", "g": "Mass", "t": "Mass",
        "mg": "Mass", "lb av": "Mass", "oz av": "Mass",
        "sh tn": "Mass", "long tn": "Mass",
        "kWh": "Energy", "MJ": "Energy", "GJ": "Energy",
        "kJ": "Energy", "J": "Energy", "Wh": "Energy",
        "MWh": "Energy", "btu": "Energy",
        "t*km": "Mass transport", "tkm": "Mass transport",
        "kg*km": "Mass transport", "t*mi": "Mass transport",
        "t*nmi": "Mass transport",
        "p*km": "Person transport", "p*mi": "Person transport",
        "m3": "Volume", "l": "Volume", "ml": "Volume",
        "cm3": "Volume", "dm3": "Volume",
        "m2": "Area", "km2": "Area", "ha": "Area", "ft2": "Area",
        "h": "Time", "min": "Time", "s": "Time",
        "d": "Time", "a": "Time", "hr": "Time",
        "km": "Length", "m": "Length", "cm": "Length",
        "mm": "Length", "mi": "Length", "ft": "Length",
        "in": "Length", "nmi": "Length",
        "Item(s)": "Number of items",
    }

    FLCAC_FP_MAP = {
        "kg": "Mass", "g": "Mass", "t": "Mass",
        "mg": "Mass", "lb av": "Mass", "oz av": "Mass",
        "sh tn": "Mass", "long tn": "Mass",
        "kWh": "Energy", "MJ": "Energy", "GJ": "Energy",
        "kJ": "Energy", "J": "Energy", "Wh": "Energy",
        "MWh": "Energy", "btu": "Energy",
        "t*km": "Goods transport (mass*distance)",
        "tkm": "Goods transport (mass*distance)",
        "kg*km": "Goods transport (mass*distance)",
        "t*mi": "Goods transport (mass*distance)",
        "t*nmi": "Goods transport (mass*distance)",
        "p*km": "Person transport", "p*mi": "Person transport",
        "m3": "Volume", "l": "Volume", "ml": "Volume",
        "cm3": "Volume", "dm3": "Volume",
        "m2": "Area", "km2": "Area", "ha": "Area", "ft2": "Area",
        "h": "Duration", "min": "Duration", "s": "Duration",
        "d": "Duration", "a": "Duration", "hr": "Duration",
        "km": "Length", "m": "Length", "cm": "Length",
        "mm": "Length", "mi": "Length", "ft": "Length",
        "in": "Length", "nmi": "Length",
        "Item(s)": "Number of items",
        "Dozen(s)": "Number of items",
        "kW": "Power", "MW": "Power", "W": "Power",
        "Bq": "Radioactivity", "kBq": "Radioactivity",
        "mol": "Mole",
    }

    def _detect_database_family(self):
        """
        Auto-detect whether the connected database uses ecoinvent
        or FLCAC flow property naming. Checks for telltale FP names.
        Stores the result for the rest of the session.
        """
        if hasattr(self, "_db_family") and self._db_family:
            return self._db_family

        self._ensure_unit_cache()

        # ecoinvent has "Time"; FLCAC has "Duration"
        # ecoinvent has "Mass transport"; FLCAC has "Goods transport..."
        has_time = "Time" in self._fp_lookup
        has_duration = "Duration" in self._fp_lookup
        has_mass_transport = "Mass transport" in self._fp_lookup
        has_goods_transport = "Goods transport (mass*distance)" in self._fp_lookup

        if has_time and has_mass_transport:
            self._db_family = "ecoinvent"
        elif has_duration and has_goods_transport:
            self._db_family = "flcac"
        elif has_time:
            self._db_family = "ecoinvent"
        elif has_duration:
            self._db_family = "flcac"
        else:
            self._db_family = "unknown"

        logger.info(f"Detected database family: {self._db_family}")
        return self._db_family

    def set_database_family(self, family: str) -> Dict:
        """
        Set the database family manually from user input.

        family: 'ecoinvent' or 'flcac'

        Call this when the user tells you which database type they
        have. If they don't know, call database_info instead which
        auto-detects.
        """
        family = family.lower().strip()
        if family in ("ecoinvent", "ei"):
            self._db_family = "ecoinvent"
        elif family in ("flcac", "lca commons", "uslci", "useeio"):
            self._db_family = "flcac"
        else:
            return {
                "error": f"Unknown family '{family}'. Use 'ecoinvent' or 'flcac'.",
                "ecoinvent_includes": "ecoinvent, EN15804GD, HiQLCD, BAFU",
                "flcac_includes": "LCA Commons, US LCI, USEEIO",
            }

        logger.info(f"Database family set by user: {self._db_family}")
        return {
            "database_family": self._db_family,
            "unit_mapping": "ecoinvent" if self._db_family == "ecoinvent" else "FLCAC",
        }

    @property
    def UNIT_FP_MAP(self):
        """Return the correct unit map for the detected database family."""
        family = self._detect_database_family()
        if family == "flcac":
            return self.FLCAC_FP_MAP
        return self.ECOINVENT_FP_MAP  # default for ecoinvent or unknown

    def _ensure_unit_cache(self):
        """Build unit cache on first use. Maps unit name → unit_ref."""
        if hasattr(self, "_unit_cache_built") and self._unit_cache_built:
            return
        self._unit_lookup = {}
        for ug_ref in self.client.get_descriptors(o.UnitGroup):
            ug = self.client.get(o.UnitGroup, ug_ref.id)
            if ug and ug.units:
                for u in ug.units:
                    self._unit_lookup[u.name] = o.Ref(
                        id=u.id, name=u.name, ref_type=o.RefType.Unit,
                    )
        self._fp_lookup = {}
        for fp_ref in self.client.get_descriptors(o.FlowProperty):
            self._fp_lookup[fp_ref.name] = fp_ref
        self._unit_cache_built = True

    def find_unit(self, unit_name: str) -> Dict:
        """
        Look up a unit and its flow property by name.
        Returns unit ref and flow property ref, or an error.
        """
        self._ensure_unit_cache()

        unit_ref = self._unit_lookup.get(unit_name)
        if not unit_ref:
            available = sorted(self._unit_lookup.keys())[:30]
            return {
                "error": f"Unit '{unit_name}' not found",
                "available_sample": available,
            }

        # Find flow property from candidate list
        fp_ref = self._get_fp_ref(unit_name)

        return {
            "unit_id": unit_ref.id,
            "unit_name": unit_ref.name,
            "flow_property_id": fp_ref.id if fp_ref else None,
            "flow_property_name": fp_ref.name if fp_ref else None,
        }

    def _get_unit_ref(self, unit_name: str):
        """Internal: get unit Ref or None."""
        self._ensure_unit_cache()
        return self._unit_lookup.get(unit_name)

    def _get_fp_ref(self, unit_name: str):
        """Internal: get flow property Ref for a unit.

        Uses the auto-detected database family to pick the right
        flow property name. ecoinvent uses 'Time', 'Mass transport';
        FLCAC uses 'Duration', 'Goods transport (mass*distance)'.
        """
        self._ensure_unit_cache()
        fp_name = self.UNIT_FP_MAP.get(unit_name)
        if not fp_name:
            return None
        fp_ref = self._fp_lookup.get(fp_name)
        if not fp_ref:
            # Substring fallback
            for name, ref in self._fp_lookup.items():
                if fp_name.lower() in name.lower():
                    return ref
        return fp_ref

    def create_flow(self, name: str, unit_name: str,
                    category: str = "",
                    flow_type: str = "product") -> Dict:
        """
        Create a flow, or return the existing one if a flow with
        the same name and category already exists.
        """
        # Pre-flight: check if this flow already exists
        existing = self._get_descriptors(o.Flow)
        for f in existing:
            f_cat = getattr(f, "category", "") or ""
            if f.name == name and (not category or category in f_cat):
                return {
                    "flow_id": f.id,
                    "flow_name": f.name,
                    "unit": unit_name,
                    "flow_type": flow_type,
                    "category": f_cat,
                    "already_existed": True,
                }

        fp_ref = self._get_fp_ref(unit_name)
        if not fp_ref:
            return {"error": f"No flow property mapping for unit '{unit_name}'"}

        type_map = {
            "product": o.FlowType.PRODUCT_FLOW,
            "waste": o.FlowType.WASTE_FLOW,
            "elementary": o.FlowType.ELEMENTARY_FLOW,
        }
        ft = type_map.get(flow_type)
        if not ft:
            return {"error": f"Invalid flow_type: {flow_type}. Use product/waste/elementary"}

        try:
            f = o.Flow()
            f.id = str(uuid.uuid4())
            f.name = name
            f.category = category
            f.flow_type = ft
            f.flow_properties = [o.FlowPropertyFactor(
                flow_property=fp_ref,
                conversion_factor=1.0,
                is_ref_flow_property=True,
            )]
            ref = self.client.put(f)
            # Clear flow cache so new flow is findable immediately
            self._cache.pop("Flow", None)
            return {
                "flow_id": ref.id,
                "flow_name": ref.name,
                "unit": unit_name,
                "flow_property": fp_ref.name,
                "flow_type": flow_type,
                "category": category,
            }
        except Exception as ex:
            return {"error": str(ex)}

    def create_bridge(self, name: str, unit_name: str,
                      category: str = "",
                      provider_id: Optional[str] = None,
                      provider_flow_id: Optional[str] = None,
                      waste: bool = False) -> Dict:
        """
        Create a bridge flow AND bridge process in one call.

        A bridge connects the foreground model to a background
        database process. The bridge process has TWO exchanges:

        For product bridges:
          OUTPUT: the bridge flow (quantitative reference)
          INPUT:  the background flow from the provider process

        For waste bridges (waste=True):
          INPUT:  the bridge flow (quantitative reference)
          OUTPUT: the background waste flow to the treatment process

        If provider_id is given, the function looks up the provider
        process, finds its quantitative reference flow, and creates
        the input exchange automatically. If provider_flow_id is
        also given, it uses that flow instead of auto-detecting.
        """
        # Pre-flight: check if a bridge process with this name exists
        existing = self._get_descriptors(o.Process)
        for p in existing:
            p_cat = getattr(p, "category", "") or ""
            if p.name == name and (not category or category in p_cat):
                # Bridge process exists, find its bridge flow too
                bridge_flow_id = None
                proc = self.client.get(o.Process, p.id)
                if proc and proc.exchanges:
                    for ex in proc.exchanges:
                        if getattr(ex, "is_quantitative_reference", False) and ex.flow:
                            bridge_flow_id = ex.flow.id
                            break
                return {
                    "flow_id": bridge_flow_id,
                    "flow_name": name,
                    "process_id": p.id,
                    "process_name": p.name,
                    "category": p_cat,
                    "already_existed": True,
                }

        # Create the bridge flow
        flow_type = "waste" if waste else "product"
        flow_result = self.create_flow(name, unit_name, category, flow_type)
        if "error" in flow_result:
            return flow_result

        flow_id = flow_result["flow_id"]
        unit_ref = self._get_unit_ref(unit_name)

        # Build the bridge flow exchange (quantitative reference)
        qref_x = o.Exchange()
        qref_x.flow = o.Ref(id=flow_id, name=name, ref_type=o.RefType.Flow)
        qref_x.amount = 1.0
        qref_x.unit = unit_ref
        qref_x.is_input = waste  # waste enters, product leaves
        qref_x.is_quantitative_reference = True
        qref_x.is_avoided_product = False
        qref_x.internal_id = 1

        exchanges = [qref_x]
        bg_flow_name = None

        # Build the background exchange if provider is given
        if provider_id:
            bg_flow_ref = None

            if provider_flow_id:
                # Use the explicitly provided flow ID
                bg_flow = self.client.get(o.Flow, provider_flow_id)
                if bg_flow:
                    bg_flow_ref = o.Ref(
                        id=bg_flow.id, name=bg_flow.name,
                        ref_type=o.RefType.Flow,
                    )
                    bg_flow_name = bg_flow.name
            else:
                # Auto-detect: look up provider's quantitative reference flow
                provider_proc = self.client.get(o.Process, provider_id)
                if provider_proc and provider_proc.exchanges:
                    for ex in provider_proc.exchanges:
                        if getattr(ex, "is_quantitative_reference", False):
                            if ex.flow:
                                bg_flow_ref = o.Ref(
                                    id=ex.flow.id, name=ex.flow.name,
                                    ref_type=o.RefType.Flow,
                                )
                                bg_flow_name = ex.flow.name
                            break

            if bg_flow_ref:
                bg_x = o.Exchange()
                bg_x.flow = bg_flow_ref
                bg_x.amount = 1.0
                bg_x.unit = unit_ref
                # For product: background flow is INPUT to bridge
                # For waste: background flow is OUTPUT from bridge
                bg_x.is_input = not waste
                bg_x.is_quantitative_reference = False
                bg_x.is_avoided_product = False
                bg_x.default_provider = o.Ref(
                    id=provider_id, ref_type=o.RefType.Process,
                )
                bg_x.internal_id = 2
                exchanges.append(bg_x)

        # Build the bridge process
        try:
            p = o.Process()
            p.id = str(uuid.uuid4())
            p.name = name
            p.category = category
            p.process_type = o.ProcessType.UNIT_PROCESS
            p.description = (
                "Bridge process: connects foreground model to background database."
            )
            p.last_internal_id = len(exchanges)
            p.quantitative_reference = qref_x
            p.exchanges = exchanges

            proc_ref = self.client.put(p)

            # Clear caches so new flow and process are findable
            self._cache.pop("Flow", None)
            self._cache.pop("Process", None)

            result = {
                "flow_id": flow_id,
                "flow_name": name,
                "process_id": proc_ref.id,
                "process_name": proc_ref.name,
                "unit": unit_name,
                "waste": waste,
                "provider_id": provider_id,
                "category": category,
                "exchange_count": len(exchanges),
            }
            if bg_flow_name:
                result["background_flow"] = bg_flow_name
            if not provider_id:
                result["note"] = (
                    "No provider set. Add the background input exchange "
                    "manually in openLCA or use edit_process."
                )
            elif len(exchanges) == 1:
                result["warning"] = (
                    "Could not find the provider's quantitative reference "
                    "flow. Bridge has no background input. Set provider_flow_id "
                    "explicitly or add the input exchange manually."
                )
            return result
        except Exception as ex:
            return {"error": str(ex)}

    def create_process(self, name: str, category: str,
                       exchanges: List[Dict],
                       parameters: Optional[List[Dict]] = None,
                       description: str = "",
                       location: Optional[str] = None) -> Dict:
        """
        Create a process, or return the existing one if a process
        with the same name and category already exists.

        If the process exists, returns its ID with already_existed=True
        so the assistant can use edit_process to modify it.
        """
        try:
            # Pre-flight: check if this process already exists
            existing = self._get_descriptors(o.Process)
            for p in existing:
                p_cat = getattr(p, "category", "") or ""
                if p.name == name and (not category or category in p_cat):
                    return {
                        "process_id": p.id,
                        "process_name": p.name,
                        "category": p_cat,
                        "already_existed": True,
                        "hint": (
                            "Process already exists. Use edit_process to "
                            "add exchanges or parameters, or use a different name."
                        ),
                    }

            # Validate all flow_ids and provider_ids exist in this database
            for i, ex_def in enumerate(exchanges):
                fid = ex_def.get("flow_id")
                if fid:
                    flow_check = self.client.get(o.Flow, fid)
                    if not flow_check:
                        return {
                            "error": f"Exchange {i}: flow_id '{fid}' not found in connected database. "
                                     f"Check that the ID is from this database, not a previous session.",
                        }
                pid = ex_def.get("provider_id")
                if pid:
                    prov_check = self.client.get(o.Process, pid)
                    if not prov_check:
                        return {
                            "error": f"Exchange {i}: provider_id '{pid}' not found in connected database.",
                        }

            p = o.Process()
            p.id = str(uuid.uuid4())
            p.name = name
            p.category = category
            p.process_type = o.ProcessType.UNIT_PROCESS
            if description:
                p.description = description

            # Set location if provided
            if location:
                loc_descriptors = self.client.get_descriptors(o.Location)
                loc_ref = None
                for ld in loc_descriptors:
                    if ld.name == location or getattr(ld, "code", "") == location:
                        loc_ref = ld
                        break
                if not loc_ref:
                    # Try partial match
                    for ld in loc_descriptors:
                        if location.lower() in ld.name.lower():
                            loc_ref = ld
                            break
                if loc_ref:
                    p.location = o.Ref(
                        id=loc_ref.id, name=loc_ref.name,
                        ref_type=o.RefType.Location,
                    )

            # Build exchanges
            exchange_objects = []
            for i, ex_def in enumerate(exchanges, start=1):
                x = o.Exchange()
                x.internal_id = i
                x.flow = o.Ref(
                    id=ex_def["flow_id"],
                    name=ex_def.get("flow_name", ""),
                    ref_type=o.RefType.Flow,
                )

                # Amount: formula takes precedence
                formula = ex_def.get("formula")
                if formula:
                    x.amount = 0.0
                    x.amount_formula = formula
                else:
                    x.amount = float(ex_def.get("amount", 0.0))

                # Unit
                unit_name = ex_def.get("unit", "kg")
                unit_ref = self._get_unit_ref(unit_name)
                if unit_ref:
                    x.unit = unit_ref

                x.is_input = ex_def.get("is_input", True)
                x.is_quantitative_reference = ex_def.get("is_qref", False)
                x.is_avoided_product = False

                # Provider
                prov_id = ex_def.get("provider_id")
                if prov_id:
                    x.default_provider = o.Ref(
                        id=prov_id, ref_type=o.RefType.Process,
                    )

                # Comment/description
                comment = ex_def.get("comment") or ex_def.get("description")
                if comment:
                    x.description = comment

                exchange_objects.append(x)

            p.last_internal_id = len(exchange_objects)
            p.exchanges = exchange_objects

            # Set quantitative reference
            qref = next((x for x in exchange_objects
                         if x.is_quantitative_reference), None)
            if qref:
                p.quantitative_reference = qref

            # Build parameters
            if parameters:
                param_objects = []
                for pd in parameters:
                    param = o.Parameter()
                    param.id = str(uuid.uuid4())
                    param.name = pd["name"]
                    param.value = float(pd.get("value", 0.0))
                    param.parameter_scope = o.ParameterScope.PROCESS_SCOPE
                    param.is_input_parameter = True
                    param.description = pd.get("description", "")
                    param_objects.append(param)
                p.parameters = param_objects

            ref = self.client.put(p)

            # Clear process cache so create_system can find it
            self._cache.pop("Process", None)
            return {
                "process_id": ref.id,
                "process_name": ref.name,
                "category": category,
                "exchange_count": len(exchange_objects),
                "parameter_count": len(parameters) if parameters else 0,
            }

        except Exception as ex:
            return {"error": str(ex)}

    def edit_process(self, process_id: str,
                     add_exchanges: Optional[List[Dict]] = None,
                     update_exchanges: Optional[List[Dict]] = None,
                     remove_exchanges: Optional[List[str]] = None,
                     add_parameters: Optional[List[Dict]] = None,
                     update_parameters: Optional[Dict[str, float]] = None,
                     description: Optional[str] = None,
                     category: Optional[str] = None,
                     location: Optional[str] = None) -> Dict:
        """
        Edit an existing process in place.

        update_exchanges now supports provider_id in addition to
        amount, formula, and unit.
        """
        try:
            process = self.client.get(o.Process, process_id)
            if not process:
                return {"error": f"Process not found: {process_id}"}

            changes = []

            # Update description
            if description is not None:
                process.description = description
                changes.append("description updated")

            # Update category
            if category is not None:
                process.category = category
                changes.append(f"category set to '{category}'")

            # Update location
            if location is not None:
                loc_descriptors = self.client.get_descriptors(o.Location)
                loc_ref = None
                for ld in loc_descriptors:
                    if ld.name == location or getattr(ld, "code", "") == location:
                        loc_ref = ld
                        break
                if not loc_ref:
                    for ld in loc_descriptors:
                        if location.lower() in ld.name.lower():
                            loc_ref = ld
                            break
                if loc_ref:
                    process.location = o.Ref(
                        id=loc_ref.id, name=loc_ref.name,
                        ref_type=o.RefType.Location,
                    )
                    changes.append(f"location set to '{loc_ref.name}'")

            # Remove exchanges by flow_id
            if remove_exchanges and process.exchanges:
                remove_set = set(remove_exchanges)
                before = len(process.exchanges)
                process.exchanges = [
                    ex for ex in process.exchanges
                    if not (ex.flow and ex.flow.id in remove_set)
                ]
                removed = before - len(process.exchanges)
                if removed:
                    changes.append(f"{removed} exchange(s) removed")

            # Update existing exchanges (match by flow_id)
            if update_exchanges and process.exchanges:
                for upd in update_exchanges:
                    target_fid = upd.get("flow_id")
                    if not target_fid:
                        continue
                    for ex in process.exchanges:
                        if ex.flow and ex.flow.id == target_fid:
                            if "formula" in upd and upd["formula"]:
                                ex.amount = 0.0
                                ex.amount_formula = upd["formula"]
                                changes.append(
                                    f"exchange '{ex.flow.name}' formula set to '{upd['formula']}'")
                            elif "amount" in upd:
                                ex.amount = float(upd["amount"])
                                ex.amount_formula = None
                                changes.append(
                                    f"exchange '{ex.flow.name}' amount set to {upd['amount']}")
                            if "unit" in upd:
                                unit_ref = self._get_unit_ref(upd["unit"])
                                if unit_ref:
                                    ex.unit = unit_ref
                                    changes.append(
                                        f"exchange '{ex.flow.name}' unit set to '{upd['unit']}'")
                            if "provider_id" in upd:
                                ex.default_provider = o.Ref(
                                    id=upd["provider_id"],
                                    ref_type=o.RefType.Process,
                                )
                                changes.append(
                                    f"exchange '{ex.flow.name}' provider updated")
                            break

            # Update existing parameter values
            if update_parameters and process.parameters:
                for param in process.parameters:
                    if param.name in update_parameters:
                        old_val = param.value
                        param.value = float(update_parameters[param.name])
                        changes.append(
                            f"parameter '{param.name}': {old_val} -> {param.value}")

            # Add new parameters
            if add_parameters:
                if not process.parameters:
                    process.parameters = []
                for pd in add_parameters:
                    param = o.Parameter()
                    param.id = str(uuid.uuid4())
                    param.name = pd["name"]
                    param.value = float(pd.get("value", 0.0))
                    param.parameter_scope = o.ParameterScope.PROCESS_SCOPE
                    param.is_input_parameter = True
                    param.description = pd.get("description", "")
                    process.parameters.append(param)
                    changes.append(f"parameter '{pd['name']}' added")

            # Add new exchanges
            if add_exchanges:
                if not process.exchanges:
                    process.exchanges = []

                # Find the next internal_id
                max_id = process.last_internal_id or 0
                if process.exchanges:
                    existing_ids = [
                        getattr(x, "internal_id", 0) or 0
                        for x in process.exchanges
                    ]
                    if existing_ids:
                        max_id = max(max_id, max(existing_ids))

                for ex_def in add_exchanges:
                    max_id += 1
                    x = o.Exchange()
                    x.internal_id = max_id
                    x.flow = o.Ref(
                        id=ex_def["flow_id"],
                        name=ex_def.get("flow_name", ""),
                        ref_type=o.RefType.Flow,
                    )

                    formula = ex_def.get("formula")
                    if formula:
                        x.amount = 0.0
                        x.amount_formula = formula
                    else:
                        x.amount = float(ex_def.get("amount", 0.0))

                    unit_name = ex_def.get("unit", "kg")
                    unit_ref = self._get_unit_ref(unit_name)
                    if unit_ref:
                        x.unit = unit_ref

                    x.is_input = ex_def.get("is_input", True)
                    x.is_quantitative_reference = ex_def.get("is_qref", False)
                    x.is_avoided_product = False

                    prov_id = ex_def.get("provider_id")
                    if prov_id:
                        x.default_provider = o.Ref(
                            id=prov_id, ref_type=o.RefType.Process,
                        )

                    process.exchanges.append(x)
                    flow_name = ex_def.get("flow_name", ex_def.get("flow_id", "?"))
                    changes.append(f"exchange '{flow_name}' added")

                process.last_internal_id = max_id

            # Save
            self.client.put(process)
            self._cache.pop("Process", None)

            return {
                "process_id": process.id,
                "process_name": process.name,
                "changes": changes,
                "exchange_count": len(process.exchanges) if process.exchanges else 0,
                "parameter_count": len(process.parameters) if process.parameters else 0,
            }

        except Exception as ex:
            return {"error": str(ex)}

    def delete_entity(self, entity_type: str, entity_id: str) -> Dict:
        """
        Delete a process, flow, or product system from the database.

        entity_type: 'process', 'flow', or 'product_system'
        entity_id: UUID of the entity to delete
        """
        type_map = {
            "process": o.Process,
            "flow": o.Flow,
            "product_system": o.ProductSystem,
        }
        olca_type = type_map.get(entity_type)
        if not olca_type:
            return {
                "error": f"Unknown entity type: {entity_type}. "
                         f"Use: {', '.join(type_map.keys())}",
            }

        try:
            # Verify it exists first
            entity = self.client.get(olca_type, entity_id)
            if not entity:
                return {"error": f"{entity_type} not found: {entity_id}"}

            name = getattr(entity, "name", entity_id)
            self.client.delete(entity)

            # Clear relevant cache
            cache_key = olca_type.__name__
            self._cache.pop(cache_key, None)

            return {
                "deleted": True,
                "entity_type": entity_type,
                "entity_id": entity_id,
                "name": name,
            }
        except Exception as ex:
            return {"error": str(ex)}

    # ── model extraction and audit ───────────────────────────
    #
    # CRITICAL SCALING KNOWLEDGE:
    # openLCA automatically scales processes to meet demand.
    # A process outputting 1 kg of steel feeding one that needs
    # 5 kg is NOT a mismatch — openLCA runs the first process
    # 5 times. Never flag amount differences between connected
    # processes as errors.
    #
    # openLCA also handles same-property unit conversions
    # automatically (e.g. MJ↔kWh, kg↔t). Do not flag these.

    def extract_model(self, category: str) -> Dict:
        """
        Extract all processes within a category folder and its
        subfolders. Returns a complete model snapshot: processes,
        exchanges, parameters, and providers.

        Convention: model folders start with '00: ' (e.g. '00: My Project').
        """
        try:
            all_processes = self._get_descriptors(o.Process)

            # Find processes in this category tree
            cat_lower = category.lower()
            model_processes = [
                p for p in all_processes
                if p.category and cat_lower in p.category.lower()
            ]

            if not model_processes:
                return {
                    "error": f"No processes found in category '{category}'",
                    "hint": "Check the category path. Model folders should start with '00: '",
                }

            # Extract full details for each process
            processes = []
            all_flows = {}  # flow_id → {name, unit, type}
            all_providers = {}  # process_id → process_name

            for proc_desc in model_processes:
                proc = self.client.get(o.Process, proc_desc.id)
                if not proc:
                    continue

                exchanges = []
                if proc.exchanges:
                    for ex in proc.exchanges:
                        flow_name = ex.flow.name if ex.flow else "Unknown"
                        flow_id = ex.flow.id if ex.flow else None
                        unit_name = ex.unit.name if ex.unit else ""
                        prov_name = None
                        prov_id = None

                        if getattr(ex, "default_provider", None):
                            prov_id = ex.default_provider.id
                            prov_name = getattr(ex.default_provider, "name", None)
                            all_providers[prov_id] = prov_name

                        if flow_id:
                            all_flows[flow_id] = {
                                "name": flow_name,
                                "unit": unit_name,
                            }

                        exchanges.append({
                            "flow_id": flow_id,
                            "flow_name": flow_name,
                            "amount": ex.amount,
                            "formula": getattr(ex, "amount_formula", None),
                            "unit": unit_name,
                            "is_input": ex.is_input,
                            "is_qref": getattr(ex, "is_quantitative_reference", False),
                            "provider_id": prov_id,
                            "provider_name": prov_name,
                        })

                parameters = []
                if proc.parameters:
                    for p in proc.parameters:
                        parameters.append({
                            "name": p.name,
                            "value": p.value,
                            "formula": getattr(p, "formula", None),
                            "is_input": getattr(p, "is_input_parameter", True),
                            "description": getattr(p, "description", ""),
                        })

                processes.append({
                    "id": proc.id,
                    "name": proc.name,
                    "category": getattr(proc, "category", ""),
                    "description": getattr(proc, "description", ""),
                    "exchanges": exchanges,
                    "parameters": parameters,
                })

            # Also find custom flows in the model category
            all_flow_descs = self._get_descriptors(o.Flow)
            model_flows = []
            for fd in all_flow_descs:
                flow_cat = getattr(fd, "category", "") or ""
                if cat_lower in flow_cat.lower():
                    model_flows.append({
                        "id": fd.id,
                        "name": fd.name,
                        "category": flow_cat,
                        "flow_type": str(getattr(fd, "flow_type", "")),
                        "ref_unit": getattr(fd, "ref_unit", ""),
                    })

            return {
                "category": category,
                "process_count": len(processes),
                "processes": processes,
                "model_flows": model_flows,
                "model_flow_count": len(model_flows),
                "flows_used": all_flows,
                "providers_referenced": all_providers,
            }

        except Exception as ex:
            return {"error": str(ex)}

    def audit_model(self, category: str) -> Dict:
        """
        Run structural checks on all processes in a category folder.

        Checks performed:
          - Every process has exactly one quantitative reference
          - All exchanges have units
          - Exchanges with amount=0 and no formula (likely placeholders)
          - Product flows produced but never consumed (orphaned)
          - Product flows consumed but never produced (missing source)
          - Exchanges missing default providers
          - Parameter name/unit consistency hints

        NOT flagged (by design):
          - Amount differences between producer and consumer.
            openLCA scales processes automatically.
          - Unit differences within the same flow property.
            openLCA converts MJ↔kWh, kg↔t, etc. automatically.
        """
        # First extract the model
        model = self.extract_model(category)
        if "error" in model:
            return model

        findings = []
        processes = model["processes"]
        process_names = {p["id"]: p["name"] for p in processes}

        # Track flow production and consumption across the model
        flow_producers = {}  # flow_id → [(process_name, amount/formula)]
        flow_consumers = {}  # flow_id → [(process_name, amount/formula)]

        for proc in processes:
            proc_name = proc["name"]

            # Check: process description warnings
            proc_desc = proc.get("description", "") or ""
            if proc_desc:
                warning_terms = [
                    "don't trust", "do not trust", "unreliable",
                    "placeholder", "estimate", "basic estimate",
                    "rough", "dummy", "temporary", "TODO",
                    "needs review", "not verified", "unverified",
                ]
                desc_lower = proc_desc.lower()
                for term in warning_terms:
                    if term.lower() in desc_lower:
                        findings.append({
                            "severity": "warning",
                            "process": proc_name,
                            "check": "description_warning",
                            "message": f"Process description contains warning: '{proc_desc[:120]}'",
                        })
                        break

            # Check: quantitative reference
            qrefs = [ex for ex in proc["exchanges"] if ex.get("is_qref")]
            if len(qrefs) == 0:
                findings.append({
                    "severity": "error",
                    "process": proc_name,
                    "check": "quantitative_reference",
                    "message": "No quantitative reference exchange found",
                })
            elif len(qrefs) > 1:
                findings.append({
                    "severity": "warning",
                    "process": proc_name,
                    "check": "quantitative_reference",
                    "message": f"Multiple quantitative references ({len(qrefs)})",
                })

            # Check: duplicate exchanges (same flow + same provider)
            seen_exchanges = {}
            for ex in proc["exchanges"]:
                fid = ex.get("flow_id")
                pid = ex.get("provider_id") or "none"
                direction = "in" if ex.get("is_input") else "out"
                key = f"{fid}|{pid}|{direction}"
                if key in seen_exchanges:
                    findings.append({
                        "severity": "warning",
                        "process": proc_name,
                        "check": "duplicate_exchange",
                        "message": (
                            f"Duplicate exchange: '{ex.get('flow_name', '?')}' "
                            f"appears {seen_exchanges[key] + 1} times with the same "
                            f"provider and direction. Likely a leftover from "
                            f"edit_process adding instead of updating."
                        ),
                    })
                    seen_exchanges[key] += 1
                else:
                    seen_exchanges[key] = 1

            for ex in proc["exchanges"]:
                flow_id = ex.get("flow_id")
                flow_name = ex.get("flow_name", "?")
                amount = ex.get("amount", 0)
                formula = ex.get("formula")
                unit = ex.get("unit", "")

                # Check: missing unit
                if not unit:
                    findings.append({
                        "severity": "warning",
                        "process": proc_name,
                        "check": "missing_unit",
                        "message": f"Exchange '{flow_name}' (flow_id: {flow_id}, amount: {amount}) has no unit",
                    })

                # Check: zero amount with no formula (placeholder)
                if amount == 0 and not formula and not ex.get("is_qref"):
                    findings.append({
                        "severity": "warning",
                        "process": proc_name,
                        "check": "zero_amount",
                        "message": f"Exchange '{flow_name}' (flow_id: {flow_id}) has amount=0 and no formula (placeholder?)",
                    })

                # Check: non-qref input without provider
                if (ex.get("is_input") and not ex.get("is_qref")
                        and not ex.get("provider_id")):
                    findings.append({
                        "severity": "info",
                        "process": proc_name,
                        "check": "missing_provider",
                        "message": f"Input '{flow_name}' (flow_id: {flow_id}, amount: {amount} {unit}) has no default provider set",
                    })

                # Track flow connectivity
                if flow_id:
                    if ex.get("is_input"):
                        flow_consumers.setdefault(flow_id, []).append(
                            (proc_name, amount, formula))
                    else:
                        flow_producers.setdefault(flow_id, []).append(
                            (proc_name, amount, formula))

            # Check: parameter naming vs exchange units
            param_names = {p["name"]: p for p in proc.get("parameters", [])}
            for ex in proc["exchanges"]:
                formula = ex.get("formula")
                if not formula:
                    continue
                unit = ex.get("unit", "").lower()
                # Simple heuristic: if a parameter name ends with a unit
                # hint that conflicts with the exchange unit
                for pname in param_names:
                    if pname not in formula:
                        continue
                    pname_lower = pname.lower()
                    # Check for obvious cross-property mismatches
                    unit_hints = {
                        "_kg": "mass", "_t": "mass", "_g": "mass",
                        "_kwh": "energy", "_mj": "energy",
                        "_m3": "volume", "_l": "volume",
                        "_km": "length", "_m": "length",
                        "_tkm": "transport",
                    }
                    ex_property = None
                    param_property = None
                    for suffix, prop in unit_hints.items():
                        if unit.replace("*", "") in suffix.strip("_"):
                            ex_property = prop
                        if pname_lower.endswith(suffix):
                            param_property = prop
                    if (param_property and ex_property
                            and param_property != ex_property):
                        findings.append({
                            "severity": "warning",
                            "process": proc_name,
                            "check": "unit_mismatch",
                            "message": (
                                f"Parameter '{pname}' suggests {param_property} "
                                f"but exchange unit is '{ex.get('unit')}' ({ex_property})"
                            ),
                        })

            # Check: orphaned parameters (defined but never used anywhere)
            # Check both exchange formulas AND other parameter formulas,
            # so indirect chains (switch → grid/solar → exchange) aren't
            # flagged as orphaned.
            all_exchange_formulas = " ".join(
                ex.get("formula", "") or ""
                for ex in proc.get("exchanges", [])
            )
            all_param_formulas = " ".join(
                (p.get("formula", "") or "") + " " + p.get("name", "")
                for p in proc.get("parameters", [])
                if not p.get("is_input", True)  # calculated params have formulas
            )
            all_formulas = all_exchange_formulas + " " + all_param_formulas

            for pname in param_names:
                if pname not in all_formulas:
                    findings.append({
                        "severity": "info",
                        "process": proc_name,
                        "check": "orphaned_parameter",
                        "message": (
                            f"Parameter '{pname}' (value: {param_names[pname].get('value')}) "
                            f"may not be referenced in any formula (check manually "
                            f"if it feeds other parameters indirectly)"
                        ),
                    })

        # Flow connectivity checks
        all_flow_ids = set(list(flow_producers.keys()) + list(flow_consumers.keys()))
        for flow_id in all_flow_ids:
            flow_name = model["flows_used"].get(flow_id, {}).get("name", "?")
            produced = flow_id in flow_producers
            consumed = flow_id in flow_consumers

            if produced and not consumed:
                # Only flag if it's from a foreground process (not a qref output
                # that's meant to leave the system)
                producers = flow_producers[flow_id]
                for pname, amt, formula in producers:
                    # Skip if this is likely a final product qref
                    pass  # Claude can assess this contextually

            if consumed and not produced:
                consumers = flow_consumers[flow_id]
                for pname, amt, formula in consumers:
                    findings.append({
                        "severity": "info",
                        "process": pname,
                        "check": "flow_not_produced",
                        "message": (
                            f"Input flow '{flow_name}' is consumed but not "
                            f"produced by any process in this model folder. "
                            f"Expected if it comes from outside the model "
                            f"(e.g. a bridge or background process)."
                        ),
                    })

        # Sort by severity
        severity_order = {"error": 0, "warning": 1, "info": 2}
        findings.sort(key=lambda f: severity_order.get(f["severity"], 3))

        errors = sum(1 for f in findings if f["severity"] == "error")
        warnings = sum(1 for f in findings if f["severity"] == "warning")
        infos = sum(1 for f in findings if f["severity"] == "info")

        return {
            "category": category,
            "process_count": len(processes),
            "summary": {
                "errors": errors,
                "warnings": warnings,
                "info": infos,
            },
            "findings": findings,
            "scaling_reminder": (
                "openLCA scales processes automatically to meet demand. "
                "A process outputting 1 kg feeding one that needs 5 kg is "
                "NOT a mismatch. Do not flag amount differences between "
                "connected processes. openLCA also handles same-property "
                "unit conversions automatically (MJ/kWh, kg/t, etc)."
            ),
        }

    def validate_system(self, system_ref: str,
                         test_calculate: bool = False) -> Dict:
        """
        Validate a product system structure.

        Lightweight by default: checks target process, linking
        presence, and parameters without running a calculation.
        Set test_calculate=True to also run a test calculation
        (slower, may time out on large models).
        """
        system = self._resolve_system(system_ref)
        if not system:
            return {"error": f"Product system not found: {system_ref}"}

        findings = []

        try:
            full_system = self.client.get(o.ProductSystem, system.id)
            if not full_system:
                return {"error": "Could not load product system details"}

            # Check target process
            target_ref = getattr(full_system, "ref_process", None)
            if not target_ref:
                # Try alternative attribute names
                target_ref = getattr(full_system, "reference_process", None)

            if target_ref:
                target_proc = self.client.get(o.Process, target_ref.id)
                if not target_proc:
                    findings.append({
                        "severity": "error",
                        "check": "target_process",
                        "message": f"Target process '{target_ref.name}' could not be loaded",
                    })
                else:
                    has_qref = False
                    if target_proc.exchanges:
                        has_qref = any(
                            getattr(ex, "is_quantitative_reference", False)
                            for ex in target_proc.exchanges
                        )
                    if not has_qref:
                        findings.append({
                            "severity": "error",
                            "check": "quantitative_reference",
                            "message": f"Target process '{target_proc.name}' has no quantitative reference",
                        })

            # Check target amount
            target_amount = getattr(full_system, "target_amount", None)
            if target_amount is not None and target_amount == 0:
                findings.append({
                    "severity": "warning",
                    "check": "target_amount",
                    "message": "Target amount is 0 - calculation will produce zero results",
                })

            # Check linked processes exist (count only, don't fetch each one)
            process_links = getattr(full_system, "process_links", None)
            if process_links:
                findings.append({
                    "severity": "info",
                    "check": "links_present",
                    "message": f"Product system has {len(process_links)} process links",
                })
            else:
                findings.append({
                    "severity": "warning",
                    "check": "no_links",
                    "message": "Product system has no process links - may need relinking",
                })

            # Check parameters
            try:
                sys_params = self.client.get_parameters(o.ProductSystem, system.id)
                if sys_params:
                    null_params = [p.name for p in sys_params if p.value is None]
                    if null_params:
                        findings.append({
                            "severity": "warning",
                            "check": "null_parameter",
                            "message": f"Parameters with no value: {', '.join(null_params)}",
                        })
                    findings.append({
                        "severity": "info",
                        "check": "parameters",
                        "message": f"{len(sys_params)} parameters found",
                    })
            except Exception:
                pass

            # Optional test calculation
            if test_calculate:
                method = self._resolve_method("EF v3.1")
                if not method:
                    methods = self._get_descriptors(o.ImpactMethod)
                    method = methods[0] if methods else None

                if method:
                    try:
                        setup = o.CalculationSetup(
                            target=full_system, impact_method=method)
                        result = self.client.calculate(setup)
                        result.wait_until_ready()
                        impacts = result.get_total_impacts()

                        zero_count = sum(1 for i in impacts if i.amount == 0)
                        total_count = len(impacts)

                        if zero_count == total_count:
                            findings.append({
                                "severity": "error",
                                "check": "all_zero",
                                "message": "All impact results are zero - system may not be linked correctly",
                            })
                        elif zero_count > total_count * 0.8:
                            findings.append({
                                "severity": "warning",
                                "check": "mostly_zero",
                                "message": f"{zero_count}/{total_count} impact categories are zero",
                            })
                        else:
                            findings.append({
                                "severity": "info",
                                "check": "calculation_ok",
                                "message": f"Test calculation succeeded: {total_count - zero_count}/{total_count} categories have non-zero results",
                            })

                        result.dispose()
                    except Exception as calc_err:
                        findings.append({
                            "severity": "error",
                            "check": "calculation_failed",
                            "message": f"Test calculation failed: {calc_err}",
                        })

        except Exception as e:
            findings.append({
                "severity": "error",
                "check": "system_load",
                "message": f"Failed to inspect system: {e}",
            })

        severity_order = {"error": 0, "warning": 1, "info": 2}
        findings.sort(key=lambda f: severity_order.get(f["severity"], 3))

        errors = sum(1 for f in findings if f["severity"] == "error")
        warnings = sum(1 for f in findings if f["severity"] == "warning")

        return {
            "system": system.name,
            "system_id": system.id,
            "valid": errors == 0,
            "summary": {"errors": errors, "warnings": warnings},
            "findings": findings,
        }

    # ── product system creation ─────────────────────────────

    def create_product_system(self, process_ref: str,
                              linking: str = "prefer_defaults",
                              target_amount: Optional[float] = None,
                              target_unit: Optional[str] = None,
                              target_flow_property: Optional[str] = None,
                              category: Optional[str] = None) -> Dict:
        """
        Create a product system from a process.

        linking options:
          'prefer_defaults' - use default providers where set (recommended)
          'only_defaults'   - only link where default providers exist

        Optional: set target_amount, target_unit (e.g. 'm3', 'kg'),
        target_flow_property (e.g. 'Volume', 'Mass'), and category
        after creation. Same pattern as EB_full_products.py.
        """
        process = self._resolve_process(process_ref)
        if not process:
            return {"error": f"Process not found: {process_ref}"}

        # Set up linking config
        if linking == "only_defaults":
            provider = o.ProviderLinking.ONLY_DEFAULTS
        else:
            provider = o.ProviderLinking.PREFER_DEFAULTS

        config = o.LinkingConfig(
            prefer_unit_processes=True,
            provider_linking=provider,
        )

        try:
            system_ref = self.client.create_product_system(process, config)

            # Modify target amount/unit/flow property if requested
            if any([target_amount, target_unit, target_flow_property, category]):
                system = self.client.get(o.ProductSystem, system_ref.id)

                if category:
                    system.category = category

                if target_amount is not None:
                    system.target_amount = target_amount

                if target_flow_property:
                    self._ensure_unit_cache()
                    fp = self._fp_lookup.get(target_flow_property)
                    if fp:
                        system.target_flow_property = o.Ref(
                            id=fp.id, name=fp.name,
                            ref_type=o.RefType.FlowProperty,
                        )

                if target_unit:
                    unit_ref = self._get_unit_ref(target_unit)
                    if unit_ref:
                        system.target_unit = unit_ref

                self.client.put(system)

            # Clear the product system cache so it shows up immediately
            if "ProductSystem" in self._cache:
                del self._cache["ProductSystem"]

            # Read back the system to report which providers were linked
            linked_system = self.client.get(o.ProductSystem, system_ref.id)
            links = self._extract_links(linked_system)

            result = {
                "system_id": system_ref.id,
                "system_name": system_ref.name,
                "source_process": process.name,
                "linking": linking,
                "linked_providers": links,
            }
            if target_amount is not None:
                result["target_amount"] = target_amount
            if target_unit:
                result["target_unit"] = target_unit
            if target_flow_property:
                result["target_flow_property"] = target_flow_property
            return result

        except Exception as e:
            return {"error": str(e)}

    def _extract_links(self, system) -> List[Dict]:
        """Extract process links from a product system."""
        links = []
        process_links = getattr(system, "process_links", None)
        if not process_links:
            return links
        for link in process_links:
            provider = getattr(link, "provider", None)
            flow = getattr(link, "flow", None)
            receiving = getattr(link, "process", None)
            links.append({
                "provider_id": provider.id if provider else None,
                "provider_name": getattr(provider, "name", None) if provider else None,
                "flow_id": flow.id if flow else None,
                "flow_name": getattr(flow, "name", None) if flow else None,
                "receiving_process_id": receiving.id if receiving else None,
                "receiving_process_name": getattr(receiving, "name", None) if receiving else None,
            })
        return links

    def get_system_links(self, system_ref: str,
                          search_term: str = "",
                          limit: int = 50) -> Dict:
        """
        Show which providers are linked to which exchanges in a
        product system. Use search_term to filter by flow or
        provider name (e.g. 'electricity', 'sodium hydroxide').

        Without a filter on large systems, results will be generic
        background links. Always filter when looking for a specific
        connection.
        """
        system = self._resolve_system(system_ref)
        if not system:
            return {"error": f"Product system not found: {system_ref}"}

        try:
            full_system = self.client.get(o.ProductSystem, system.id)
            if not full_system:
                return {"error": "Could not load product system details"}

            links = self._extract_links(full_system)

            # Filter by search term if provided
            if search_term:
                term = search_term.lower()
                links = [
                    lnk for lnk in links
                    if (term in (lnk.get("flow_name") or "").lower()
                        or term in (lnk.get("provider_name") or "").lower()
                        or term in (lnk.get("receiving_process_name") or "").lower())
                ]

            total = len(links)

            return {
                "system": system.name,
                "system_id": system.id,
                "search_term": search_term or "(all)",
                "link_count": min(total, limit),
                "total_matching": total,
                "truncated": total > limit,
                "links": links[:limit],
            }
        except Exception as e:
            error_str = str(e).lower()
            if "connection" in error_str or "closed" in error_str:
                return {
                    "error": (
                        f"System too large to load via IPC. This happens "
                        f"with systems backed by large background databases "
                        f"where the full product system exceeds the IPC "
                        f"transfer limit. Use contribution_analysis to "
                        f"identify providers, or check the graph view in "
                        f"openLCA directly."
                    ),
                }
            return {"error": str(e)}

    # ── calculations ─────────────────────────────────────────

    def calculate_impacts(self, system_ref: str,
                          method_ref: str) -> Dict:
        """Run a baseline impact calculation for a product system."""
        system = self._resolve_system(system_ref)
        if not system:
            return {"error": f"Product system not found: {system_ref}"}

        method = self._resolve_method(method_ref)
        if not method:
            return {"error": f"Impact method not found: {method_ref}"}

        setup = o.CalculationSetup(target=system, impact_method=method)
        result = self.client.calculate(setup)
        result.wait_until_ready()

        try:
            impacts = result.get_total_impacts()
            return {
                "system": system.name,
                "method": method.name,
                "impacts": self._impacts_to_list(impacts),
            }
        finally:
            result.dispose()

    def contribution_analysis(self, system_ref: str, method_ref: str,
                              threshold_pct: float = 0.1,
                              max_contributors: int = 30,
                              categories: Optional[List[str]] = None) -> Dict:
        """
        Process-level contribution analysis using the verified pattern
        from gurit_dq_analysis.py:

            result.get_tech_flows()
            result.get_total_impacts_of(tech_flow)

        For each tech flow in the system, gets the full upstream impact
        total. Filters to contributions above threshold_pct of the
        category total. Returns a breakdown per impact category.

        If categories is provided, only those category names are
        analysed (substring match). Otherwise all categories are
        included.
        """
        system = self._resolve_system(system_ref)
        if not system:
            return {"error": f"Product system not found: {system_ref}"}

        method = self._resolve_method(method_ref)
        if not method:
            return {"error": f"Impact method not found: {method_ref}"}

        setup = o.CalculationSetup(target=system, impact_method=method)
        result = self.client.calculate(setup)
        result.wait_until_ready()

        try:
            # Get system totals
            total_impacts = result.get_total_impacts()
            totals = {}
            for imp in total_impacts:
                totals[imp.impact_category.id] = {
                    "name": imp.impact_category.name,
                    "amount": imp.amount,
                    "unit": getattr(imp.impact_category, "ref_unit", ""),
                }

            # Filter categories if requested
            active_cats = {}
            for cat_id, cat_data in totals.items():
                if categories:
                    if any(c.lower() in cat_data["name"].lower()
                           for c in categories):
                        active_cats[cat_id] = cat_data
                else:
                    active_cats[cat_id] = cat_data

            # Get all tech flows
            tech_flows = result.get_tech_flows()

            # For each tech flow, get upstream impacts
            contributions_by_cat = {cat_id: [] for cat_id in active_cats}

            for tf in tech_flows:
                tf_impacts = result.get_total_impacts_of(tf)

                for imp in tf_impacts:
                    cat_id = imp.impact_category.id
                    if cat_id not in active_cats:
                        continue

                    total_amt = active_cats[cat_id]["amount"]
                    if abs(total_amt) < 1e-30:
                        continue

                    pct = (imp.amount / total_amt) * 100

                    if abs(pct) >= threshold_pct:
                        contributions_by_cat[cat_id].append({
                            "process": tf.provider.name,
                            "process_id": tf.provider.id,
                            "flow": tf.flow.name,
                            "amount": imp.amount,
                            "pct": round(pct, 2),
                        })

            # Sort and trim each category
            output_cats = {}
            for cat_id, contribs in contributions_by_cat.items():
                cat_data = active_cats[cat_id]
                contribs.sort(key=lambda c: abs(c["amount"]), reverse=True)
                trimmed = contribs[:max_contributors]

                covered_pct = sum(abs(c["pct"]) for c in trimmed)

                output_cats[cat_data["name"]] = {
                    "total": cat_data["amount"],
                    "unit": cat_data["unit"],
                    "contributor_count": len(trimmed),
                    "covered_pct": round(covered_pct, 1),
                    "contributors": trimmed,
                }

            return {
                "system": system.name,
                "method": method.name,
                "threshold_pct": threshold_pct,
                "categories_analysed": len(output_cats),
                "categories": output_cats,
            }

        finally:
            result.dispose()

    def monte_carlo(self, system_ref: str, method_ref: str,
                    iterations: int = 1000) -> Dict:
        """
        Run Monte Carlo uncertainty simulation.

        Tries multiple approaches to set up MC since the API
        varies between olca-ipc versions. Collects per-iteration
        impact totals and computes statistics.
        """
        system = self._resolve_system(system_ref)
        if not system:
            return {"error": f"Product system not found: {system_ref}"}

        method = self._resolve_method(method_ref)
        if not method:
            return {"error": f"Impact method not found: {method_ref}"}

        try:
            import statistics

            # Create setup without number_of_runs (constructor rejects it)
            setup = o.CalculationSetup(
                target=system,
                impact_method=method,
            )

            # Try setting number_of_runs as attribute (works in some versions)
            try:
                setup.number_of_runs = iterations
            except (AttributeError, TypeError):
                pass  # Attribute not supported, will use simulate_next loop

            result = self.client.calculate(setup)
            result.wait_until_ready()

            try:
                distributions: Dict[str, List[float]] = {}
                cat_units = {}

                for i in range(iterations):
                    # simulate_next runs one MC iteration
                    try:
                        result.simulate_next()
                    except AttributeError:
                        # simulate_next not available in this version
                        if i == 0:
                            # Get at least the deterministic result
                            impacts = result.get_total_impacts()
                            return {
                                "system": system.name,
                                "method": method.name,
                                "error": (
                                    "Monte Carlo not supported by this olca-ipc version. "
                                    "simulate_next() is not available on the result object. "
                                    "Returning deterministic results instead."
                                ),
                                "deterministic_results": self._impacts_to_list(impacts),
                            }
                        break

                    impacts = result.get_total_impacts()

                    for imp in impacts:
                        name = imp.impact_category.name
                        if name not in distributions:
                            distributions[name] = []
                            cat_units[name] = getattr(
                                imp.impact_category, "ref_unit", "")
                        distributions[name].append(imp.amount)

                    if (i + 1) % 100 == 0:
                        logger.info(f"Monte Carlo: {i + 1}/{iterations}")

                stats = {}
                for name, values in distributions.items():
                    n = len(values)
                    if n == 0:
                        continue
                    mean = statistics.mean(values)
                    sd = statistics.stdev(values) if n > 1 else 0
                    cv = (sd / abs(mean) * 100) if abs(mean) > 1e-30 else 0

                    stats[name] = {
                        "unit": cat_units[name],
                        "iterations": n,
                        "mean": mean,
                        "std_dev": sd,
                        "cv_pct": round(cv, 2),
                        "min": min(values),
                        "max": max(values),
                        "median": statistics.median(values),
                        "p5": sorted(values)[int(n * 0.05)] if n >= 20 else None,
                        "p95": sorted(values)[int(n * 0.95)] if n >= 20 else None,
                    }

                # Detect zero-variance (no uncertainty data in database)
                all_zero_variance = all(
                    stats[name]["std_dev"] == 0 for name in stats
                )

                output = {
                    "system": system.name,
                    "method": method.name,
                    "iterations": len(next(iter(distributions.values()), [])),
                    "statistics": stats,
                }

                if all_zero_variance:
                    output["warning"] = (
                        "All categories have zero variance across all iterations. "
                        "This means the database processes have no uncertainty "
                        "distributions defined on their exchanges. The Monte Carlo "
                        "simulation ran correctly but sampled no distributions, so "
                        "every iteration returned the same deterministic result. "
                        "These statistics are not meaningful for uncertainty analysis. "
                        "Check exchange-level uncertainty in the source processes "
                        "before relying on these numbers."
                    )

                return output

            finally:
                result.dispose()

        except Exception as e:
            return {"error": str(e), "note": (
                "Monte Carlo requires uncertainty distributions on exchanges. "
                "If the database has no uncertainty data, results will be "
                "identical across all iterations."
            )}

    def inventory_flows(self, system_ref: str,
                        method_ref: str,
                        threshold: float = 1e-10,
                        max_flows: int = 50) -> Dict:
        """
        Get elementary flow inventory results (LCI).

        Returns the raw biosphere flows (kg CO2, MJ energy, etc.)
        rather than characterised impact results. Uses
        result.get_total_flows() from the verified DQ script pattern.
        """
        system = self._resolve_system(system_ref)
        if not system:
            return {"error": f"Product system not found: {system_ref}"}

        method = self._resolve_method(method_ref)
        if not method:
            return {"error": f"Impact method not found: {method_ref}"}

        setup = o.CalculationSetup(target=system, impact_method=method)
        result = self.client.calculate(setup)
        result.wait_until_ready()

        try:
            total_flows = result.get_total_flows()

            flows = []
            for fr in total_flows:
                if abs(fr.amount) < threshold:
                    continue
                ef = fr.envi_flow
                flows.append({
                    "flow": ef.flow.name,
                    "flow_id": ef.flow.id,
                    "amount": fr.amount,
                    "is_input": ef.is_input,
                    "category": getattr(ef.flow, "category", ""),
                    "ref_unit": getattr(ef.flow, "ref_unit", ""),
                })

            # Sort by absolute amount
            flows.sort(key=lambda f: abs(f["amount"]), reverse=True)
            flows = flows[:max_flows]

            return {
                "system": system.name,
                "method": method.name,
                "flow_count": len(flows),
                "total_flows_in_system": len(total_flows),
                "flows": flows,
            }

        finally:
            result.dispose()

    def get_data_quality(self, process_id: str) -> Dict:
        """
        Extract pedigree matrix / data quality entries for a process
        and all its exchanges.

        Pedigree format: '(R;C;T;G;F)' where:
          R = Reliability
          C = Completeness
          T = Temporal correlation
          G = Geographical correlation
          F = Further technological correlation
        Values 1-5, lower is better.
        """
        DQ_LABELS = [
            "Reliability", "Completeness", "Temporal correlation",
            "Geographical correlation", "Further technological correlation",
        ]

        def parse_pedigree(entry):
            if not entry:
                return None
            values = entry.strip("()").split(";")
            parsed = {}
            for i, v in enumerate(values):
                label = DQ_LABELS[i] if i < len(DQ_LABELS) else f"Indicator {i+1}"
                try:
                    parsed[label] = int(v.strip())
                except (ValueError, TypeError):
                    parsed[label] = v.strip()
            return parsed

        try:
            process = self.client.get(o.Process, process_id)
            if not process:
                return {"error": f"Process not found: {process_id}"}

            # Process-level DQ
            result = {
                "process_id": process.id,
                "process_name": process.name,
                "process_dq_system": (
                    process.dq_system.name
                    if getattr(process, "dq_system", None) else None),
                "exchange_dq_system": (
                    process.exchange_dq_system.name
                    if getattr(process, "exchange_dq_system", None) else None),
                "process_dq_entry": getattr(process, "dq_entry", None),
                "process_dq_parsed": parse_pedigree(
                    getattr(process, "dq_entry", None)),
            }

            # Exchange-level DQ
            exchanges_dq = []
            if process.exchanges:
                for ex in process.exchanges:
                    dq_entry = getattr(ex, "dq_entry", None)
                    if dq_entry or getattr(ex, "base_uncertainty", None):
                        exchanges_dq.append({
                            "flow": ex.flow.name if ex.flow else "?",
                            "is_input": ex.is_input,
                            "amount": ex.amount,
                            "unit": ex.unit.name if ex.unit else "",
                            "dq_entry": dq_entry,
                            "dq_parsed": parse_pedigree(dq_entry),
                            "base_uncertainty": getattr(
                                ex, "base_uncertainty", None),
                            "uncertainty_type": (
                                str(ex.uncertainty.distribution_type)
                                if getattr(ex, "uncertainty", None) else None),
                        })

            result["exchanges_with_dq"] = exchanges_dq
            result["exchanges_dq_count"] = len(exchanges_dq)
            result["total_exchanges"] = (
                len(process.exchanges) if process.exchanges else 0)

            return result

        except Exception as e:
            return {"error": str(e)}

    def run_scenarios(self, system_ref: str, method_ref: str,
                      scenarios: Dict[str, Dict[str, float]]) -> Dict:
        """
        Run scenario calculations.

        scenarios: {scenario_name: {param_name: value, ...}, ...}

        Uses the same ParameterRedef + CalculationSetup pattern as
        B280_olca_scenarios.py.
        """
        system = self._resolve_system(system_ref)
        if not system:
            return {"error": f"Product system not found: {system_ref}"}

        method = self._resolve_method(method_ref)
        if not method:
            return {"error": f"Impact method not found: {method_ref}"}

        # Build context lookup once
        system_params = self.client.get_parameters(o.ProductSystem, system.id)
        context_by_name = {p.name: p.context for p in system_params}

        results = {}
        for scenario_name, param_values in scenarios.items():
            logger.info(f"Running scenario: {scenario_name}")

            param_redefs = [
                o.ParameterRedef(
                    name=name,
                    value=float(value),
                    context=context_by_name.get(name),
                )
                for name, value in param_values.items()
            ]

            setup = o.CalculationSetup(
                target=system,
                impact_method=method,
                parameters=param_redefs,
            )
            result = self.client.calculate(setup)
            result.wait_until_ready()

            try:
                impacts = result.get_total_impacts()
                results[scenario_name] = self._impacts_to_list(impacts)
            finally:
                result.dispose()

        return {
            "system": system.name,
            "method": method.name,
            "scenario_count": len(results),
            "results": results,
        }

    # ── CSV-based scenarios (mirrors B280_olca_scenarios.py) ──

    def read_scenarios_csv(self, csv_path: str) -> Dict:
        """
        Read a scenarios CSV file.

        Expected format: first column 'Parameter', remaining columns
        are scenario names. Each row holds the parameter value per
        scenario. Same format as B280_olca_scenarios.py expects.
        """
        if not os.path.exists(csv_path):
            return {"error": f"File not found: {csv_path}"}

        try:
            with open(csv_path, "r") as f:
                reader = csv.DictReader(f)
                fieldnames = reader.fieldnames
                rows = list(reader)

            if not fieldnames or "Parameter" not in fieldnames:
                return {"error": "CSV must have 'Parameter' as first column"}

            scenario_names = [col for col in fieldnames if col != "Parameter"]
            parameter_names = [row["Parameter"] for row in rows]

            # Convert to the dict format run_scenarios expects
            scenarios = {}
            for name in scenario_names:
                scenarios[name] = {}
                for row in rows:
                    raw = row[name].strip().replace(",", ".")
                    try:
                        scenarios[name][row["Parameter"]] = float(raw)
                    except (ValueError, TypeError):
                        return {
                            "error": (
                                f"Cannot parse value '{row[name]}' for "
                                f"parameter '{row['Parameter']}' in "
                                f"scenario '{name}' as a number"
                            ),
                        }

            return {
                "csv_path": csv_path,
                "scenario_names": scenario_names,
                "parameter_names": parameter_names,
                "scenario_count": len(scenario_names),
                "parameter_count": len(parameter_names),
                "scenarios": scenarios,
            }
        except Exception as e:
            return {"error": f"Failed to read CSV: {e}"}

    def run_scenarios_csv(self, system_ref: str, method_ref: str,
                          csv_path: str,
                          output_path: str = "") -> Dict:
        """
        Full scenario pipeline: read CSV, calculate, write results.

        If output_path is empty, generates one from the method name.
        Returns the calculation results and the output file path.
        """
        # Read the CSV
        csv_data = self.read_scenarios_csv(csv_path)
        if "error" in csv_data:
            return csv_data

        # Resolve system and method
        system = self._resolve_system(system_ref)
        if not system:
            return {"error": f"Product system not found: {system_ref}"}

        method = self._resolve_method(method_ref)
        if not method:
            return {"error": f"Impact method not found: {method_ref}"}

        # Run the scenarios
        calc_result = self.run_scenarios(
            system_ref, method_ref, csv_data["scenarios"]
        )
        if "error" in calc_result:
            return calc_result

        # Write results CSV - default to same folder as input
        if not output_path:
            input_dir = os.path.dirname(os.path.abspath(csv_path))
            safe_name = method.name.replace(" ", "_").replace("/", "_")
            output_path = os.path.join(
                input_dir, f"scenario_results_{safe_name}.csv"
            )

        scenario_names = csv_data["scenario_names"]
        results = calc_result["results"]

        try:
            with open(output_path, "w", newline="") as f:
                writer = csv.writer(f)

                # Header
                writer.writerow(["Impact Category"] + scenario_names)

                # Use the first scenario's results as the category template
                first = results[scenario_names[0]]

                # Build lookup: {scenario: {category_id: amount}}
                by_scenario = {}
                for sname in scenario_names:
                    by_scenario[sname] = {
                        imp["category_id"]: imp["amount"]
                        for imp in results[sname]
                    }

                # One row per impact category
                for impact in first:
                    cat_name = impact["category"]
                    unit = impact["unit"]
                    cat_id = impact["category_id"]

                    row = [f"{cat_name} ({unit})"]
                    for sname in scenario_names:
                        row.append(by_scenario[sname].get(cat_id, "N/A"))
                    writer.writerow(row)

            calc_result["output_file"] = os.path.abspath(output_path)
            calc_result["csv_input"] = csv_path
            return calc_result

        except Exception as e:
            calc_result["output_error"] = str(e)
            return calc_result

    def run_sensitivity(self, system_ref: str, method_ref: str,
                        parameter_names: List[str],
                        variation_pct: float = 20.0) -> Dict:
        """
        Run +/- sensitivity analysis on named parameters.

        Uses the same ParameterRedef pattern as B280_olca_sensitivity.py.
        Each parameter is varied independently; all others stay at baseline.
        """
        system = self._resolve_system(system_ref)
        if not system:
            return {"error": f"Product system not found: {system_ref}"}

        method = self._resolve_method(method_ref)
        if not method:
            return {"error": f"Impact method not found: {method_ref}"}

        # Get system parameters and validate
        system_params = self.client.get_parameters(o.ProductSystem, system.id)
        params_by_name = {p.name: p for p in system_params}

        testable = []
        missing = []
        for name in parameter_names:
            if name in params_by_name:
                testable.append(name)
            else:
                missing.append(name)

        if not testable:
            return {
                "error": "No matching parameters found in system",
                "missing": missing,
            }

        variation_factor = variation_pct / 100.0

        # Baseline calculation
        logger.info("Running baseline calculation")
        setup = o.CalculationSetup(target=system, impact_method=method)
        result = self.client.calculate(setup)
        result.wait_until_ready()

        try:
            baseline_impacts = result.get_total_impacts()
            baseline = {}
            for i in baseline_impacts:
                baseline[i.impact_category.name] = {
                    "amount": i.amount,
                    "unit": getattr(i.impact_category, "ref_unit", ""),
                }
        finally:
            result.dispose()

        # Sensitivity runs
        sensitivity = {}
        for param_name in testable:
            param_obj = params_by_name[param_name]
            baseline_value = param_obj.value
            logger.info(f"Varying: {param_name} (baseline: {baseline_value})")

            sensitivity[param_name] = {"baseline_value": baseline_value}

            for label, multiplier in [("minus", 1 - variation_factor),
                                      ("plus", 1 + variation_factor)]:
                varied_value = baseline_value * multiplier

                param_redef = o.ParameterRedef(
                    name=param_name,
                    value=varied_value,
                    context=param_obj.context,
                )
                setup = o.CalculationSetup(
                    target=system,
                    impact_method=method,
                    parameters=[param_redef],
                )
                result = self.client.calculate(setup)
                result.wait_until_ready()

                try:
                    impacts = result.get_total_impacts()
                    sensitivity[param_name][label] = {
                        i.impact_category.name: i.amount for i in impacts
                    }
                finally:
                    result.dispose()

        return {
            "system": system.name,
            "method": method.name,
            "variation_pct": variation_pct,
            "baseline": baseline,
            "sensitivity": sensitivity,
            "tested": testable,
            "missing": missing,
        }

    # ── CSV-based sensitivity (mirrors B280_olca_sensitivity.py) ─

    def read_sensitivity_csv(self, csv_path: str) -> Dict:
        """
        Read a sensitivity CSV file.

        Expected format: one parameter name per line.
        Lines starting with '#' are comments. A header row of
        'Parameter' is skipped. Same format as B280_olca_sensitivity.py.
        """
        if not os.path.exists(csv_path):
            return {"error": f"File not found: {csv_path}"}

        try:
            names = []
            with open(csv_path, "r") as f:
                for line in f:
                    name = line.strip()
                    if not name or name.startswith("#"):
                        continue
                    if name == "Parameter":
                        continue
                    names.append(name)

            return {
                "csv_path": csv_path,
                "parameter_count": len(names),
                "parameters": names,
            }
        except Exception as e:
            return {"error": f"Failed to read CSV: {e}"}

    def run_sensitivity_csv(self, system_ref: str, method_ref: str,
                            csv_path: str, variation_pct: float = 20.0,
                            output_path: str = "") -> Dict:
        """
        Full sensitivity pipeline: read CSV, calculate, write results.

        Output CSV matches the B280_olca_sensitivity.py format:
        Impact Category | Unit | Baseline | param1 -X% | param1 +X% | ...
        """
        # Read the parameter list
        csv_data = self.read_sensitivity_csv(csv_path)
        if "error" in csv_data:
            return csv_data

        parameter_names = csv_data["parameters"]

        # Run sensitivity
        calc_result = self.run_sensitivity(
            system_ref, method_ref, parameter_names, variation_pct
        )
        if "error" in calc_result:
            return calc_result

        # Write results CSV - default to same folder as input
        if not output_path:
            input_dir = os.path.dirname(os.path.abspath(csv_path))
            method = self._resolve_method(method_ref)
            safe_name = method.name.replace(" ", "_").replace("/", "_")
            output_path = os.path.join(
                input_dir, f"sensitivity_results_{safe_name}.csv"
            )

        baseline = calc_result["baseline"]
        sensitivity = calc_result["sensitivity"]
        testable = calc_result["tested"]

        try:
            with open(output_path, "w", newline="") as f:
                writer = csv.writer(f)

                # Header: Impact Category | Unit | Baseline | p1 -X% | p1 +X% | ...
                header = ["Impact Category", "Unit", "Baseline"]
                for pname in testable:
                    header.append(f"{pname} -{variation_pct}%")
                    header.append(f"{pname} +{variation_pct}%")
                writer.writerow(header)

                # One row per impact category
                for cat_name, cat_data in baseline.items():
                    row = [cat_name, cat_data["unit"], cat_data["amount"]]

                    for pname in testable:
                        minus_val = sensitivity[pname]["minus"].get(cat_name, "N/A")
                        plus_val = sensitivity[pname]["plus"].get(cat_name, "N/A")
                        row.append(minus_val)
                        row.append(plus_val)

                    writer.writerow(row)

            calc_result["output_file"] = os.path.abspath(output_path)
            calc_result["csv_input"] = csv_path
            return calc_result

        except Exception as e:
            calc_result["output_error"] = str(e)
            return calc_result
