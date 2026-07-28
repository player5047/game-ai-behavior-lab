"""generative_agents.memory.schedule"""

import datetime

from modules import utils


def _parse_date(date_str):
    if not date_str:
        return None
    for date_format in ("%Y%m%d-%H:%M:%S", "%Y%m%d-%H:%M"):
        try:
            return utils.to_date(date_str, date_format)
        except ValueError:
            continue
    return utils.to_date(date_str)


class Schedule:
    EN_SLEEP_MARKERS = ("sleeping", "asleep", "in bed", "sleep", "bed")
    CN_SLEEP_MARKERS = ("睡", "床", "就寝", "入睡", "安睡")

    def __init__(
        self,
        create=None,
        daily_schedule=None,
        diversity=5,
        max_try=5,
        mode="generated",
        manual_daily_schedule=None,
        cycle_minutes=24 * 60,
        cycle_start=None,
    ):
        if create:
            self.create = _parse_date(create)
        else:
            self.create = None
        self.daily_schedule = daily_schedule or []
        self.diversity = diversity
        self.max_try = max_try
        self.mode = mode
        self.manual_daily_schedule = manual_daily_schedule or []
        self.cycle_minutes = max(1, int(cycle_minutes or 24 * 60))
        self.cycle_start = _parse_date(cycle_start)

    def abstract(self):
        def _to_stamp(plan):
            start, end = self.plan_stamps(plan, time_format="%H:%M")
            return "{}~{}".format(start, end)

        des = {}
        for plan in self.daily_schedule:
            stamp = _to_stamp(plan)
            if plan.get("decompose"):
                s_info = {_to_stamp(p): p["describe"] for p in plan["decompose"]}
                des[stamp + ": " + plan["describe"]] = s_info
            else:
                des[stamp] = plan["describe"]
        return des

    def __str__(self):
        return utils.dump_dict(self.abstract())

    def add_plan(self, describe, duration, decompose=None):
        if self.daily_schedule:
            last_plan = self.daily_schedule[-1]
            start = last_plan["start"] + last_plan["duration"]
        else:
            start = 0
        self.daily_schedule.append(
            {
                "idx": len(self.daily_schedule),
                "describe": describe,
                "start": start,
                "duration": duration,
                "decompose": decompose or {},
            }
        )
        return self.daily_schedule[-1]

    def use_manual_schedule(self):
        self.daily_schedule = []
        start = 0
        for entry in self.manual_daily_schedule:
            if isinstance(entry, dict):
                start = int(entry.get("start", start))
                duration = int(entry["duration"])
                describe = entry["describe"]
            else:
                if len(entry) == 3:
                    start, duration, describe = entry
                    start = int(start)
                    duration = int(duration)
                else:
                    duration, describe = entry
                    duration = int(duration)
            decompose = [
                {
                    "idx": 0,
                    "describe": describe,
                    "start": start,
                    "duration": duration,
                }
            ]
            self.daily_schedule.append(
                {
                    "idx": len(self.daily_schedule),
                    "describe": describe,
                    "start": start,
                    "duration": duration,
                    "decompose": decompose,
                }
            )
            start += duration

    def _cycle_base(self):
        if self.mode != "manual":
            return None
        if not self.cycle_start:
            self.cycle_start = utils.get_timer().get_date()
        elapsed = max(0, utils.get_timer().get_delta(self.cycle_start))
        cycle_index = elapsed // self.cycle_minutes
        return self.cycle_start + datetime.timedelta(
            minutes=cycle_index * self.cycle_minutes
        )

    def _current_minute(self):
        if self.mode == "manual":
            base = self._cycle_base()
            return max(0, utils.get_timer().get_delta(base)) % self.cycle_minutes
        return utils.get_timer().daily_duration()

    def time_at(self, minutes):
        if self.mode == "manual":
            return self._cycle_base() + datetime.timedelta(minutes=minutes)
        return utils.get_timer().daily_time(minutes)

    def minute_at(self, date):
        if self.mode == "manual":
            return max(0, utils.get_timer().get_delta(self._cycle_base(), date))
        return utils.daily_duration(date)

    def current_plan(self):
        total_minute = self._current_minute()
        for plan in self.daily_schedule:
            if self.plan_stamps(plan)[1] <= total_minute:
                continue
            for de_plan in plan.get("decompose", []):
                if self.plan_stamps(de_plan)[1] <= total_minute:
                    continue
                return plan, de_plan
            return plan, plan
        last_plan = self.daily_schedule[-1]
        return last_plan, last_plan

    def plan_stamps(self, plan, time_format=None):
        def _to_date(minutes):
            return self.time_at(minutes).strftime(time_format)

        start, end = plan["start"], plan["start"] + plan["duration"]
        if time_format:
            start, end = _to_date(start), _to_date(end)
        return start, end

    @classmethod
    def is_sleep_describe(cls, describe):
        describe = str(describe or "")
        lower_describe = describe.lower()
        return any(marker in lower_describe for marker in cls.EN_SLEEP_MARKERS) or any(
            marker in describe for marker in cls.CN_SLEEP_MARKERS
        )

    def decompose(self, plan):
        d_plan = plan.get("decompose", {})
        describe = plan["describe"]
        if self.is_sleep_describe(describe):
            plan["decompose"] = {}
            return False
        if len(d_plan) > 0:
            return False
        return True

    def scheduled(self):
        if not self.daily_schedule:
            return False
        if self.mode == "manual":
            return True
        return utils.get_timer().daily_format() == self.create.strftime("%A %B %d")

    def to_dict(self):
        return {
            "create": (
                self.create.strftime("%Y%m%d-%H:%M:%S") if self.create else None
            ),
            "daily_schedule": self.daily_schedule,
            "mode": self.mode,
            "manual_daily_schedule": self.manual_daily_schedule,
            "cycle_minutes": self.cycle_minutes,
            "cycle_start": (
                self.cycle_start.strftime("%Y%m%d-%H:%M:%S")
                if self.cycle_start
                else None
            ),
        }
