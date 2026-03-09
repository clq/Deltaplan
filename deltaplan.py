"""Deltaplan API client — handles authentication and schedule fetching.

Key API endpoints:
  POST /API/login              — authenticate (form: username, password)
  GET  /API/login              — get user info (after auth)
  GET  /API/departments        — list departments
  GET  /API/shifttypes         — list shift types (vagttyper)
  GET  /API/employees-schedule — get shifts (params: emp_id, date_from, date_to, employees)
  GET  /API/employees-schedule/schedule — full view (own, colleagues, vacant)
  GET  /API/dashboard-frontpage — dashboard incl. vacant_shifts, shifts_on_dates, etc.
"""

import json
import os
import requests

BASE_URL = "https://deltaplan.dk/deltaplan_v2/classic"
API_URL = f"{BASE_URL}/API"

CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")


def load_config():
    with open(CONFIG_PATH) as f:
        return json.load(f)


class DeltaplanClient:
    def __init__(self, config=None):
        self.config = config or load_config()
        self.session = requests.Session()
        self.user = None
        self._shift_type_map = None

    def login(self):
        """Authenticate and populate session cookies + user info."""
        resp = self.session.post(
            f"{API_URL}/login",
            data={
                "username": self.config["username"],
                "password": self.config["password"],
            },
            headers={"Referer": f"{BASE_URL}/"},
            allow_redirects=False,
        )

        location = resp.headers.get("location", "")
        if "err=" in location:
            err_msg = location.split("err=")[-1].split("&")[0]
            raise RuntimeError(f"Login failed: {requests.utils.unquote(err_msg)}")

        if resp.status_code not in (200, 302):
            raise RuntimeError(f"Login failed with HTTP {resp.status_code}")

        # Fetch user info via GET /API/login
        user_resp = self.session.get(f"{API_URL}/login", headers=self._api_headers())
        if user_resp.ok:
            data = user_resp.json()
            if data.get("success") and data.get("data"):
                self.user = data["data"]

        if not self.user:
            self.user = self._user_from_cookies()

        return self.user

    def _user_from_cookies(self):
        """Extract user info from session cookies as a fallback."""
        import base64
        cookies = self.session.cookies.get_dict()
        user = {}
        for key, field in [("vs_medarb_id", "medarbejder_id"),
                           ("vs_virksomhed_id", "virksomhed_id")]:
            if key in cookies:
                try:
                    user[field] = base64.b64decode(
                        requests.utils.unquote(cookies[key])
                    ).decode()
                except Exception:
                    user[field] = cookies[key]
        return user

    def _api_headers(self):
        """Common headers for API requests, mirroring the frontend JS."""
        headers = {
            "Referer": f"{BASE_URL}/",
            "Accept": "application/json",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
        }
        if self.user:
            if "medarbejder_id" in self.user:
                headers["User-Id"] = str(self.user["medarbejder_id"])
            if "virksomhed_id" in self.user:
                headers["User-Company-Id"] = str(self.user["virksomhed_id"])
        return headers

    # ── Data endpoints ──────────────────────────────────────────────

    def get_departments(self):
        """Fetch available departments (afdelinger)."""
        resp = self.session.get(f"{API_URL}/departments", headers=self._api_headers())
        resp.raise_for_status()
        return resp.json()

    def get_shift_types(self):
        """Fetch shift types (vagttyper) and cache them."""
        if self._shift_type_map is not None:
            return self._shift_type_map
        resp = self.session.get(f"{API_URL}/shifttypes", headers=self._api_headers())
        resp.raise_for_status()
        data = resp.json()
        self._shift_type_map = {}
        if data.get("success"):
            for st in data["data"]["rows"]:
                self._shift_type_map[st["vagttype_id"]] = st
        return self._shift_type_map

    def get_my_shifts(self, date_from, date_to):
        """Fetch the logged-in user's own shifts for a date range."""
        emp_id = self.user["medarbejder_id"]
        resp = self.session.get(
            f"{API_URL}/employees-schedule",
            headers=self._api_headers(),
            params={
                "emp_id": emp_id,
                "date_from": date_from,
                "date_to": date_to,
                "employees": str(emp_id),
            },
        )
        resp.raise_for_status()
        return resp.json()

    def get_full_schedule(self, date_from, date_to):
        """Fetch the full schedule view: own shifts, colleagues, vacants.

        This is the main endpoint that returns everything visible in the
        Deltaplan schedule UI.
        """
        resp = self.session.get(
            f"{API_URL}/employees-schedule/schedule",
            headers=self._api_headers(),
            params=[
                ("method", "GET"),
                ("period[]", date_from),
                ("period[]", date_to),
            ],
        )
        resp.raise_for_status()
        data = resp.json()
        if not data.get("success"):
            raise RuntimeError(f"Schedule fetch failed: {data}")
        return data["data"]

    def get_dashboard(self):
        """Fetch the dashboard which includes vacant shifts, own shifts, etc."""
        resp = self.session.get(
            f"{API_URL}/dashboard-frontpage", headers=self._api_headers()
        )
        resp.raise_for_status()
        return resp.json()

    def get_vacant_shifts(self):
        """Get currently available vacant shifts from the dashboard.

        Returns a dict keyed by date, each value is a list of shift objects.
        """
        data = self.get_dashboard()
        if data.get("success"):
            return data["data"].get("vacant_shifts", [])
        return []

    def get_vacant_shifts_by_type(self, type_abbreviations=None):
        """Get vacant shifts filtered by shift type abbreviations.

        Args:
            type_abbreviations: List like ["FP 1", "FP 2", "E 3"].
                                If None, uses config["shift_types"].
        """
        if type_abbreviations is None:
            type_abbreviations = self.config.get("shift_types", [])

        # Resolve abbreviations to IDs
        shift_types = self.get_shift_types()
        abbr_to_id = {
            st["vagttype_forkortelse"]: st["vagttype_id"]
            for st in shift_types.values()
        }
        target_ids = set()
        for abbr in type_abbreviations:
            if abbr in abbr_to_id:
                target_ids.add(abbr_to_id[abbr])

        vacant = self.get_vacant_shifts()

        if not target_ids:
            return vacant  # no filter, return all

        # Filter: vacant_shifts can be a list or dict-by-date
        if isinstance(vacant, dict):
            filtered = {}
            for date, shifts in vacant.items():
                matching = [s for s in shifts if s.get("vagttype_id") in target_ids]
                if matching:
                    filtered[date] = matching
            return filtered
        elif isinstance(vacant, list):
            return [s for s in vacant if s.get("vagttype_id") in target_ids]
        return vacant

    def enrich_shift(self, shift):
        """Add human-readable shift type name to a shift dict."""
        shift_types = self.get_shift_types()
        st = shift_types.get(str(shift.get("vagttype_id", "")))
        if st:
            shift["_shift_type_name"] = st["vagttype_navn"]
            shift["_shift_type_abbr"] = st["vagttype_forkortelse"]
        return shift

    def get_enriched_schedule(self, date_from, date_to, target_types=None):
        """Fetch the full schedule and enrich colleague shifts with type info.

        The schedule endpoint hides shift_type for colleagues, so we fetch
        each colleague's shifts individually to get vagttype_id, then merge.
        All colleague shifts with a known shift type are included (filtering
        is done client-side).

        Args:
            target_types: unused, kept for API compat. Filtering is client-side.
        """
        import time as _time

        schedule = self.get_full_schedule(date_from, date_to)
        shift_types = self.get_shift_types()

        # Build type-ID → abbreviation map
        id_to_abbr = {
            sid: st["vagttype_forkortelse"] for sid, st in shift_types.items()
        }

        # Collect unique colleague employee IDs + names from schedule
        emp_ids = set()
        emp_names = {}
        for shifts in schedule.get("colleagues_shifts", {}).values():
            for s in shifts:
                eid = s.get("employee_id")
                if eid:
                    emp_ids.add(eid)
                    emp_names[eid] = s.get("employee_name", "?")

        # Fetch each colleague's shifts to get vagttype_id
        enriched_colleagues = {}  # date → [shift, …]
        seen_types = set()
        for eid in emp_ids:
            resp = self.session.get(
                f"{API_URL}/employees-schedule",
                headers=self._api_headers(),
                params={
                    "emp_id": eid,
                    "date_from": date_from,
                    "date_to": date_to,
                    "employees": eid,
                },
            )
            if not resp.ok:
                continue
            data = resp.json()
            if not data.get("success") or not data.get("data"):
                continue
            for s in data["data"]:
                abbr = id_to_abbr.get(str(s.get("vagttype_id", "")), "")
                if not abbr:
                    continue
                seen_types.add(abbr)
                date = s["vagt_dato"]
                enriched_colleagues.setdefault(date, []).append({
                    "date": date,
                    "time_start": s["vagt_start"][:5],
                    "time_end": s["vagt_slut"][:5],
                    "employee_name": emp_names.get(eid, str(eid)),
                    "employee_id": eid,
                    "shift_type": abbr,
                    "department_name": "Resepsjon",
                    "status": s.get("status", ""),
                    "vagt_id": s.get("vagt_id", ""),
                })
            _time.sleep(0.05)  # be polite to the server

        # Sort each date's list
        for shifts in enriched_colleagues.values():
            shifts.sort(key=lambda s: s["time_start"])

        schedule["colleagues_shifts"] = enriched_colleagues
        schedule["available_shift_types"] = sorted(seen_types)
        return schedule


def ensure_data_dir():
    os.makedirs(DATA_DIR, exist_ok=True)
