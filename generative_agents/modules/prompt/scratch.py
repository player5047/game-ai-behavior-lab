import random
import datetime
import re
from string import Template
from pydantic import BaseModel, Field
from collections import namedtuple
from typing import Dict, List, Tuple
from modules import utils
from modules.memory import Event


Result = namedtuple("Result", ["prompt", "callback", "failsafe", "return_type"])

class Scratch:
    def __init__(self, name, currently, config):
        self.name = name
        self.currently = currently
        self.config = config
        self.template_path = "data/prompts"
        self.werewolf_context = {}

    def build_prompt(self, template, data):
        with open(f"{self.template_path}/{template}.txt", "r", encoding="utf-8") as file:
            file_content = file.read()

        template = Template(file_content)
        filled_content = template.substitute(data)

        return filled_content

    def set_werewolf_context(self, context):
        self.werewolf_context = context or {}

    def _base_desc(self):
        base_desc = self.build_prompt(
            "base_desc",
            {
                "name": self.name,
                "age": self.config["age"],
                "innate": self.config["innate"],
                "learned": self.config["learned"],
                "lifestyle": self.config["lifestyle"],
                "daily_plan": self.config["daily_plan"],
                "date": utils.get_timer().daily_format_cn(),
                "currently": self.currently,
            }
        )
        werewolf_desc = self._werewolf_desc()
        if werewolf_desc:
            base_desc += "\n\n" + werewolf_desc
        return base_desc

    def _werewolf_desc(self):
        context = self.werewolf_context
        if not context or not context.get("enabled"):
            return ""
        candidates = context.get("candidate_targets", [])
        if isinstance(candidates, list):
            candidates = "、".join(candidates) if candidates else "无"
        checked = "是" if context.get("checked_magic_mirror_today") else "否"
        return """狼人杀游戏规则与当前状态：
{public_rules}

当前轮次：第{round}轮
当前阶段：{phase_name}（{phase}）
当前夜间子阶段：{night_stage_name}
你的身份：{role}
你的阵营：{team}
你是否存活：{alive}
今天是否已查看魔镜：{checked}
最近一次魔镜公开公告：{magic_mirror_message}
魔镜给你的私密提示：{private_message}
当前阶段私密指示：{phase_instruction}
你当前需要做的事：{required_action}
你当前可选择的目标：{candidate_targets}

请根据以上信息行动，不要使用魔镜没有告诉你的信息。""".format(
            public_rules=context.get("public_rules", ""),
            round=context.get("round", ""),
            phase_name=context.get("phase_name", ""),
            phase=context.get("phase", ""),
            night_stage_name=context.get("night_stage_name", ""),
            role=context.get("role", "未分配"),
            team=context.get("team", "未知"),
            alive="是" if context.get("alive", True) else "否",
            checked=checked,
            magic_mirror_message=context.get("magic_mirror_message", ""),
            private_message=context.get("private_message", ""),
            phase_instruction=context.get("phase_instruction", ""),
            required_action=context.get("required_action", ""),
            candidate_targets=candidates,
        )

    def prompt_poignancy_event(self, event):
        prompt = self.build_prompt(
            "poignancy_event",
            {
                "base_desc": self._base_desc(),
                "agent": self.name,
                "event": event.get_describe(),
            }
        )

        class PoignancyEventResponse(BaseModel):
            res: int = Field(description="事件的情感强度评分，整数，范围1到10")

        return Result(prompt, None, random.choice(list(range(10))) + 1, PoignancyEventResponse)

    def prompt_poignancy_chat(self, event):
        prompt = self.build_prompt(
            "poignancy_chat",
            {
                "base_desc": self._base_desc(),
                "agent": self.name,
                "event": event.get_describe(),
            }
        )

        class PoignancyChatResponse(BaseModel):
            res: int = Field(description="对话的情感强度评分，整数，范围1到10")

        return Result(prompt, None, random.choice(list(range(10))) + 1, PoignancyChatResponse)

    def prompt_wake_up(self):
        prompt = self.build_prompt(
            "wake_up",
            {
                "base_desc": self._base_desc(),
                "lifestyle": self.config["lifestyle"],
                "agent": self.name,
            }
        )

        class wakeupResponse(BaseModel):
            res: int = Field(description="起床时间，24小时制的小时数，整数，范围0到11")

        def _callback(response):
            value = response
            if value > 11:
                value = 11
            return value

        return Result(prompt, _callback, 8, wakeupResponse)

    def prompt_schedule_init(self, wake_up):
        prompt = self.build_prompt(
            "schedule_init",
            {
                "base_desc": self._base_desc(),
                "lifestyle": self.config["lifestyle"],
                "agent": self.name,
                "wake_up": wake_up,
            }
        )

        class schedule_initResponse(BaseModel):
            res: list[str] = Field(description="按时间顺序排列的日程活动列表，每项为简短的活动描述")

        def _callback(response):
            assert len(response) >= 3, "schedule_init: too few items"
            return response

        failsafe = [
            "早上6点起床并完成早餐的例行工作",
            "早上7点吃早餐",
            "早上8点看书",
            "中午12点吃午饭",
            "下午1点小睡一会儿",
            "晚上7点放松一下，看电视",
            "晚上11点睡觉",
        ]
        return Result(prompt, _callback, failsafe, schedule_initResponse)

    def prompt_schedule_daily(self, wake_up, daily_schedule):
        hourly_schedule = ""
        for i in range(wake_up):
            hourly_schedule += f"[{i}:00] 睡觉\n"
        for i in range(wake_up, 24):
            hourly_schedule += f"[{i}:00] <活动>\n"

        prompt = self.build_prompt(
            "schedule_daily",
            {
                "base_desc": self._base_desc(),
                "agent": self.name,
                "daily_schedule": "；".join(daily_schedule),
                "hourly_schedule": hourly_schedule,
            }
        )

        class schedule_dailyResponse(BaseModel):
            res: dict[str, str] = Field(description="24小时日程表，键为时间字符串如'8:00'，值为该时段的活动描述")

        failsafe = {
            "6:00": "起床并完成早晨的例行工作",
            "7:00": "吃早餐",
            "8:00": "读书",
            "9:00": "读书",
            "10:00": "读书",
            "11:00": "读书",
            "12:00": "吃午饭",
            "13:00": "小睡一会儿",
            "14:00": "小睡一会儿",
            "15:00": "小睡一会儿",
            "16:00": "继续工作",
            "17:00": "继续工作",
            "18:00": "回家",
            "19:00": "放松，看电视",
            "20:00": "放松，看电视",
            "21:00": "睡前看书",
            "22:00": "准备睡觉",
            "23:00": "睡觉",
        }

        def _callback(response):
            assert len(response) >= 5, "less than 5 schedules"
            return response

        return Result(prompt, _callback, failsafe, schedule_dailyResponse)

    def prompt_schedule_decompose(self, plan, schedule):
        def _plan_des(plan):
            start, end = schedule.plan_stamps(plan, time_format="%H:%M")
            return f'{start} 至 {end}，{self.name} 计划 {plan["describe"]}'

        indices = range(
            max(plan["idx"] - 1, 0), min(plan["idx"] + 2, len(schedule.daily_schedule))
        )

        start, end = schedule.plan_stamps(plan, time_format="%H:%M")
        increment = max(int(plan["duration"] / 100) * 5, 5)

        prompt = self.build_prompt(
            "schedule_decompose",
            {
                "base_desc": self._base_desc(),
                "agent": self.name,
                "plan": "；".join([_plan_des(schedule.daily_schedule[i]) for i in indices]),
                "increment": increment,
                "start": start,
                "end": end,
            }
        )

        class schedule_decomposeResponse(BaseModel):
            res: List[Tuple[str, int]] = Field(description="子任务列表，每项为 [活动描述, 时长分钟数] 的元组")

        def _callback(response):
            left = plan["duration"] - sum([s[1] for s in response])
            if left > 0:
                response.append((plan["describe"], left))
            return response

        failsafe = [(plan["describe"], 10) for _ in range(int(plan["duration"] / 10))]
        return Result(prompt, _callback, failsafe, schedule_decomposeResponse)

    def prompt_schedule_revise(self, action, schedule):
        plan, _ = schedule.current_plan()
        start, end = schedule.plan_stamps(plan, time_format="%H:%M")
        act_start_minutes = schedule.minute_at(action.start)
        original_plan, new_plan = [], []

        def _plan_des(start, end, describe):
            if not isinstance(start, str):
                start = start.strftime("%H:%M")
            if not isinstance(end, str):
                end = end.strftime("%H:%M")
            return "[{} 至 {}] {}".format(start, end, describe)

        for de_plan in plan["decompose"]:
            de_start, de_end = schedule.plan_stamps(de_plan, time_format="%H:%M")
            original_plan.append(_plan_des(de_start, de_end, de_plan["describe"]))
            if de_plan["start"] + de_plan["duration"] <= act_start_minutes:
                new_plan.append(_plan_des(de_start, de_end, de_plan["describe"]))
            elif de_plan["start"] <= act_start_minutes:
                new_plan.extend(
                    [
                        _plan_des(de_start, action.start, de_plan["describe"]),
                        _plan_des(
                            action.start, action.end, action.event.get_describe(False)
                        ),
                    ]
                )

        original_plan, new_plan = "\n".join(original_plan), "\n".join(new_plan)

        prompt = self.build_prompt(
            "schedule_revise",
            {
                "agent": self.name,
                "start": start,
                "end": end,
                "original_plan": original_plan,
                "duration": action.duration,
                "event": action.event.get_describe(),
                "new_plan": new_plan,
            }
        )

        class schedule_reviseResponse(BaseModel):
            res: List[Tuple[str, str, str]] = Field(description="调整后的完整日程列表，每项为 [开始时间, 结束时间, 活动描述] 的元组，时间格式为 HH:MM")

        def _callback(response):  
            # response已经是List[Tuple[str, str, str]]类型  
            # 格式: [(开始时间, 结束时间, 描述), ...]  
            decompose = []  
            for start, end, describe in response:  
                m_start = utils.daily_duration(utils.to_date(start, "%H:%M"))  
                m_end = utils.daily_duration(utils.to_date(end, "%H:%M"))  
                decompose.append(  
                    {  
                        "idx": len(decompose),  
                        "describe": describe,  
                        "start": m_start,  
                        "duration": m_end - m_start,  
                    }  
                )  
            return decompose

        return Result(prompt, _callback, plan["decompose"], schedule_reviseResponse)

    def prompt_determine_sector(self, describes, spatial, address, tile):
        live_address = spatial.find_address("living_area", as_list=True)[:-1]
        curr_address = tile.get_address("sector", as_list=True)

        prompt = self.build_prompt(
            "determine_sector",
            {
                "agent": self.name,
                "live_sector": live_address[-1],
                "live_arenas": ", ".join(i for i in spatial.get_leaves(live_address)),
                "current_sector": curr_address[-1],
                "current_arenas": ", ".join(i for i in spatial.get_leaves(curr_address)),
                "daily_plan": self.config["daily_plan"],
                "areas": ", ".join(i for i in spatial.get_leaves(address)),
                "complete_plan": describes[0],
                "decomposed_plan": describes[1],
            }
        )

        sectors = spatial.get_leaves(address)
        arenas = {}
        for sec in sectors:
            arenas.update(
                {a: sec for a in spatial.get_leaves(address + [sec]) if a not in arenas}
            )
        failsafe = random.choice(sectors) if sectors else (address[-1] if address else "")

        class determine_sectorResponse(BaseModel):
            res: str = Field(description="从给定列表中选出的目标区域名称，必须与列表中的某项完全一致")

        def _callback(response):  
            # response已经是str类型  
            # 验证sector是否在有效列表中，或进行映射  
            if response in sectors:  
                return response  
            if response in arenas:  
                return arenas[response]  
            for s in sectors:  
                if response.startswith(s):  
                    return s  
            return failsafe
        return Result(prompt, _callback, failsafe, determine_sectorResponse)

    def prompt_determine_arena(self, describes, spatial, address):
        prompt = self.build_prompt(
            "determine_arena",
            {
                "agent": self.name,
                "target_sector": address[-1],
                "target_arenas": ", ".join(i for i in spatial.get_leaves(address)),
                "daily_plan": self.config["daily_plan"],
                "complete_plan": describes[0],
                "decomposed_plan": describes[1],
            }
        )

        arenas = spatial.get_leaves(address)
        failsafe = random.choice(arenas) if arenas else (address[-1] if address else "")

        class determine_arenaResponse(BaseModel):
            res: str = Field(description="从给定列表中选出的目标场所名称，必须与列表中的某项完全一致")

        def _callback(response):
            return response if response in arenas else failsafe

        return Result(prompt, _callback, failsafe, determine_arenaResponse)

    def prompt_determine_object(self, describes, spatial, address):
        objects = spatial.get_leaves(address)

        prompt = self.build_prompt(
            "determine_object",
            {
                "activity": describes[1],
                "objects": ", ".join(objects),
            }
        )

        failsafe = random.choice(objects) if objects else (address[-1] if address else "")

        class determine_objectResponse(BaseModel):
            res: str = Field(description="从给定列表中选出的最相关对象名称，必须与列表中的某项完全一致")
        def _callback(response):
            # pattern = ["The most relevant object from the Objects is: <(.+?)>", "<(.+?)>"]
            return response if response in objects else failsafe

        return Result(prompt, _callback, failsafe, determine_objectResponse)

    def prompt_describe_event(self, subject, describe, address, emoji=None):
        prompt = self.build_prompt(
            "describe_event",
            {
                "action": describe,
            }
        )

        e_describe = describe.replace("(", "").replace(")", "").replace("<", "").replace(">", "")
        if e_describe.startswith(subject + "此时"):
            e_describe = e_describe.replace(subject + "此时", "")
        failsafe = Event(
            subject, "此时", e_describe, describe=describe, address=address, emoji=emoji
        )
        class describe_eventResponse(BaseModel):
            res: List[Tuple[str, str, str]] = Field(description="动作的三元组列表，每项为 [主语, 谓语, 宾语]")

        def _callback(response):  
            # response已经是List[Tuple[str, str, str]]类型  
            # 格式: [(主语, 谓语, 宾语), ...]  
            for subject, predicate, obj in response:  
                # 验证三元组不为空  
                if subject and predicate and obj:  
                    return Event(subject, predicate, obj, describe=describe, address=address, emoji=emoji)  
            return None
        return Result(prompt, _callback, failsafe, describe_eventResponse)

    def prompt_describe_object(self, obj, describe):
        prompt = self.build_prompt(
            "describe_object",
            {
                "object": obj,
                "agent": self.name,
                "action": describe,
            }
        )

        class DescribeObjectResponse(BaseModel):
            res: str = Field(description="物品的状态描述，不超过10个字的短句，不要包含物品名称")

        def _callback(response):
            response = response.strip()
            # 移除 "物品名" 前缀
            if response.startswith(obj):
                response = response[len(obj):].strip()
            return response or failsafe

        failsafe = "空闲"
        return Result(prompt, _callback, failsafe, DescribeObjectResponse)

    def prompt_werewolf_select_target(self, context):
        candidates = context.get("candidate_targets", [])
        if isinstance(candidates, str):
            candidates = [i.strip() for i in candidates.split("、") if i.strip()]
        failsafe = candidates[0] if candidates else "放弃"
        prompt = self.build_prompt(
            "werewolf_select_target",
            {
                "agent": self.name,
                "round": context.get("round", ""),
                "phase_name": context.get("phase_name", ""),
                "role": context.get("role", "未分配"),
                "team": context.get("team", "未知"),
                "magic_mirror_message": context.get("magic_mirror_message", ""),
                "private_message": context.get("private_message", ""),
                "phase_instruction": context.get("phase_instruction", ""),
                "required_action": context.get("required_action", ""),
                "candidate_targets": "、".join(candidates) if candidates else "无",
                "speech_history": context.get("speech_history", "暂无正式发言"),
                "wolf_discussion_history": context.get("wolf_discussion_history", "暂无狼人讨论"),
            }
        )

        class werewolfSelectTargetResponse(BaseModel):
            res: str = Field(description="从合法候选列表中选择的目标名字，必须与列表中的某项完全一致")

        def _callback(response):
            if response in candidates:
                return response
            response = str(response)
            for candidate in candidates:
                if candidate in response:
                    return candidate
            return failsafe

        return Result(prompt, _callback, failsafe, werewolfSelectTargetResponse)

    def prompt_werewolf_morning_speech(self, context):
        order = context.get("speech_order", [])
        if isinstance(order, str):
            order_text = order
        else:
            order_text = "、".join(order) if order else "暂无"
        alive_players = context.get("alive_players", [])
        if isinstance(alive_players, str):
            alive_text = alive_players
        else:
            alive_text = "、".join(alive_players) if alive_players else "暂无"
        dead_last_night = context.get("dead_last_night", [])
        if isinstance(dead_last_night, str):
            deaths_text = dead_last_night
        else:
            deaths_text = "、".join(dead_last_night) if dead_last_night else "无人死亡"

        failsafe = "我会根据魔镜公开信息、大家的发言和投票行为继续观察，不会把私人关系当作身份结论。"
        prompt = self.build_prompt(
            "werewolf_morning_speech",
            {
                "agent": self.name,
                "round": context.get("round", ""),
                "phase_name": context.get("phase_name", ""),
                "role": context.get("role", "未分配"),
                "team": context.get("team", "未知"),
                "alive_players": alive_text,
                "dead_last_night": deaths_text,
                "exiled_player": context.get("exiled_player") or "暂无",
                "magic_mirror_message": context.get("magic_mirror_message", ""),
                "private_message": context.get("private_message", ""),
                "phase_instruction": context.get("phase_instruction", ""),
                "speech_order": order_text,
                "speech_history": context.get("speech_history", "暂无正式发言"),
            }
        )

        class werewolfMorningSpeechResponse(BaseModel):
            res: str = Field(description="玩家在上午会议中的正式发言，2到5句话")

        def _callback(response):
            response = str(response or "").strip()
            for prefix in (self.name + "：", self.name + ":"):
                if response.startswith(prefix):
                    response = response[len(prefix):].strip()
            return response or failsafe

        return Result(prompt, _callback, failsafe, werewolfMorningSpeechResponse)

    def prompt_werewolf_discuss_kill(self, context):
        candidates = context.get("candidate_targets", [])
        if isinstance(candidates, str):
            candidates = [i.strip() for i in candidates.split("、") if i.strip()]
        fallback_target = candidates[0] if candidates else "放弃"
        fallback = {
            "target": fallback_target,
            "message": "我建议今晚击杀{}，先削弱对狼人阵营威胁最大的目标。".format(
                fallback_target
            ),
        }
        prompt = self.build_prompt(
            "werewolf_discuss_kill",
            {
                "agent": self.name,
                "round": context.get("round", ""),
                "phase_name": context.get("phase_name", ""),
                "role": context.get("role", "未分配"),
                "team": context.get("team", "未知"),
                "magic_mirror_message": context.get("magic_mirror_message", ""),
                "private_message": context.get("private_message", ""),
                "phase_instruction": context.get("phase_instruction", ""),
                "candidate_targets": "、".join(candidates) if candidates else "无",
                "speech_history": context.get("speech_history", "暂无正式发言"),
                "wolf_discussion_history": context.get("wolf_discussion_history", "暂无狼人讨论"),
            }
        )

        class werewolfDiscussKillResponse(BaseModel):
            res: Dict[str, str] = Field(
                description="包含 target 和 message 的对象，target 必须来自合法候选列表"
            )

        def _candidate_from_text(text):
            text = str(text or "").strip()
            if text in candidates:
                return text
            for candidate in candidates:
                if candidate in text:
                    return candidate
            return fallback_target

        def _callback(response):
            if isinstance(response, str):
                target = _candidate_from_text(response)
                message = response.strip()
            else:
                data = dict(response or {})
                target = _candidate_from_text(data.get("target"))
                message = str(data.get("message") or "").strip()
            if not message:
                message = fallback["message"]
            for prefix in (self.name + "：", self.name + ":"):
                if message.startswith(prefix):
                    message = message[len(prefix):].strip()
            if target not in candidates:
                target = fallback_target
            return {"target": target, "message": message}

        return Result(prompt, _callback, fallback, werewolfDiscussKillResponse)

    def prompt_werewolf_rank_speech_order(self, context):
        candidates = context.get("candidate_targets", [])
        if isinstance(candidates, str):
            candidates = [i.strip() for i in candidates.split("、") if i.strip()]

        preferences = context.get("speech_preferences", {})
        preference_lines = []
        for candidate in candidates:
            preference = preferences.get(candidate, {}).get("preference", "无所谓")
            preference_lines.append("{}：{}".format(candidate, preference))

        failsafe = list(candidates)
        prompt = self.build_prompt(
            "werewolf_rank_speech_order",
            {
                "agent": self.name,
                "round": context.get("round", ""),
                "phase_name": context.get("phase_name", ""),
                "role": context.get("role", "未分配"),
                "team": context.get("team", "未知"),
                "magic_mirror_message": context.get("magic_mirror_message", ""),
                "private_message": context.get("private_message", ""),
                "phase_instruction": context.get("phase_instruction", ""),
                "required_action": context.get("required_action", ""),
                "candidate_targets": "、".join(candidates) if candidates else "无",
                "speech_preferences": "\n".join(preference_lines) or "暂无申报",
            }
        )

        class werewolfRankSpeechOrderResponse(BaseModel):
            res: List[str] = Field(
                description="完整发言顺序列表，必须包含每一名候选玩家且不能包含候选列表外的名字"
            )

        def _candidate_from_text(text):
            text = str(text or "").strip()
            if text in candidates:
                return text
            for candidate in candidates:
                if candidate in text:
                    return candidate
            return None

        def _callback(response):
            if isinstance(response, str):
                items = [response]
            else:
                items = list(response or [])
            if len(items) == 1 and isinstance(items[0], str):
                indexed = []
                for candidate in candidates:
                    pos = items[0].find(candidate)
                    if pos >= 0:
                        indexed.append((pos, candidate))
                if indexed:
                    items = [candidate for _, candidate in sorted(indexed)]

            order = []
            for item in items:
                candidate = _candidate_from_text(item)
                if candidate and candidate not in order:
                    order.append(candidate)
            order.extend(candidate for candidate in candidates if candidate not in order)
            return order if sorted(order) == sorted(candidates) else failsafe

        return Result(prompt, _callback, failsafe, werewolfRankSpeechOrderResponse)

    def prompt_decide_chat(self, agent, other, focus, chats):
        def _status_des(a):
            event = a.get_event()
            if a.path:
                return f"{a.name} 正去往 {event.get_describe(False)}"
            return event.get_describe()

        context = "。".join(
            [c.describe for c in focus["events"]]
        )
        context += "\n" + "。".join([c.describe for c in focus["thoughts"]]) 
        date_str = utils.get_timer().get_date("%Y-%m-%d %H:%M:%S")
        chat_history = ""
        if chats:
            chat_history = f" {agent.name} 和 {other.name} 上次在 {chats[0].create} 聊过关于 {chats[0].describe} 的话题"
        a_des, o_des = _status_des(agent), _status_des(other)

        prompt = self.build_prompt(
            "decide_chat",
            {
                "context": context,
                "date": date_str,
                "chat_history": chat_history,
                "agent_status": a_des,
                "another_status": o_des,
                "agent": agent.name,
                "another": other.name,
            }
        )

        class decide_chatResponse(BaseModel):
            res: bool = Field(description="是否主动发起对话，true 表示会主动对话，false 表示不会")

        def _callback(response):
            if isinstance(response, bool):
                return response
            return str(response).strip().lower() in ("true", "yes", "是", "1")

        failsafe = False
        return Result(prompt, _callback, failsafe, decide_chatResponse)

    def prompt_decide_chat_terminate(self, agent, other, chats):
        conversation = "\n".join(["{}: {}".format(n, u) for n, u in chats])
        conversation = (
            conversation or "[对话尚未开始]"
        )

        prompt = self.build_prompt(
            "decide_chat_terminate",
            {
                "conversation": conversation,
                "agent": agent.name,
                "another": other.name,
            }
        )

        class decide_chat_terminateResponse(BaseModel):
            res: bool = Field(description="对话是否已告一段落，true 表示对话结束，false 表示对话仍在继续")

        def _callback(response):
            if isinstance(response, bool):
                return response
            return str(response).strip().lower() in ("true", "yes", "是", "1")

        failsafe = False
        return Result(prompt, _callback, failsafe, decide_chat_terminateResponse)

    def prompt_decide_wait(self, agent, other, focus):
        example1 = self.build_prompt(
            "decide_wait_example",
            {
                "context": "简是丽兹的室友。2022-10-25 07:05，简和丽兹互相问候了早上好。",
                "date": "2022-10-25 07:09",
                "agent": "简",
                "another": "丽兹",
                "status": "简 正要去浴室",
                "another_status": "丽兹 已经在 使用浴室",
                "action": "使用浴室",
                "another_action": "使用浴室",
                "reason": "推理：简和丽兹都想用浴室。简和丽兹同时使用浴室会很奇怪。所以，既然丽兹已经在用浴室了，对简来说最好的选择就是等着用浴室。\n",
                "answer": "答案：<选项A>",
            }
        )
        example2 = self.build_prompt(
            "decide_wait_example",
            {
                "context": "山姆是莎拉的朋友。2022-10-24 23:00，山姆和莎拉就最喜欢的电影进行了交谈。",
                "date": "2022-10-25 12:40",
                "agent": "山姆",
                "another": "莎拉",
                "status": "山姆 正要去吃午饭",
                "another_status": "莎拉 已经在 洗衣服",
                "action": "吃午饭",
                "another_action": "洗衣服",
                "reason": "推理：山姆可能会在餐厅吃午饭。莎拉可能会去洗衣房洗衣服。由于山姆和莎拉需要使用不同的区域，他们的行为并不冲突。所以，由于山姆和莎拉将在不同的区域，山姆现在继续吃午饭。\n",
                "answer": "答案：<选项B>",
            }
        )

        def _status_des(a):
            event, loc = a.get_event(), ""
            if event.address:
                loc = " 在 {} 的 {}".format(event.address[-2], event.address[-1])
            if not a.path:
                return f"{a.name} 已经在 {event.get_describe(False)}{loc}"
            return f"{a.name} 正要去 {event.get_describe(False)}{loc}"

        context = ". ".join(
            [c.describe for c in focus["events"]]
        )
        context += "\n" + ". ".join([c.describe for c in focus["thoughts"]])

        task = self.build_prompt(
            "decide_wait_example",
            {
                "context": context,
                "date": utils.get_timer().get_date("%Y-%m-%d %H:%M"),
                "agent": agent.name,
                "another": other.name,
                "status": _status_des(agent),
                "another_status": _status_des(other),
                "action": agent.get_event().get_describe(False),
                "another_action": other.get_event().get_describe(False),
                "reason": "",
                "answer": "",
            }
        )

        prompt = self.build_prompt(
            "decide_wait",
            {
                "examples_1": example1,
                "examples_2": example2,
                "task": task,
            }
        )

        class decide_waitResponse(BaseModel):
            res: str = Field(description="选择的选项，'A' 表示等待，'B' 表示继续当前行动")

        def _callback(response):
            return "A" in response

        failsafe = False
        return Result(prompt, _callback, failsafe, decide_waitResponse)

    def prompt_summarize_relation(self, agent, other_name):
        nodes = agent.associate.retrieve_focus([other_name], 50)

        prompt = self.build_prompt(
            "summarize_relation",
            {
                "context": "\n".join(["{}. {}".format(idx, n.describe) for idx, n in enumerate(nodes)]),
                "agent": agent.name,
                "another": other_name,
            }
        )
        failsafe = agent.name + " 正在看着 " + other_name
        class summarize_relationResponse(BaseModel):
            res: str = Field(description="一句话描述两人之间的关系，以第三人称表述")

        def _callback(response):
            return response.strip() or failsafe

        return Result(prompt, _callback, failsafe, summarize_relationResponse)

    def prompt_generate_chat(self, agent, other, relation, chats):
        focus = [relation, other.get_event().get_describe()]
        if len(chats) > 4:
            focus.append("; ".join("{}: {}".format(n, t) for n, t in chats[-4:]))
        nodes = agent.associate.retrieve_focus(focus, 15)
        memory = "\n- " + "\n- ".join([n.describe for n in nodes])
        chat_nodes = agent.associate.retrieve_chats(other.name)
        pass_context = ""
        for n in chat_nodes:
            delta = utils.get_timer().get_delta(n.create)
            if delta > 480:
                continue
            pass_context += f"{delta} 分钟前，{agent.name} 和 {other.name} 进行过对话。{n.describe}\n"

        address = agent.get_tile().get_address()
        if len(pass_context) > 0:
            prev_context = f'\n背景：\n"""\n{pass_context}"""\n\n'
        else:
            prev_context = ""
        curr_context = (
            f"{agent.name} {agent.get_event().get_describe(False)} 时，看到 {other.name} {other.get_event().get_describe(False)}。"
        )

        conversation = "\n".join(["{}: {}".format(n, u) for n, u in chats])
        conversation = (
            conversation or "[对话尚未开始]"
        )

        prompt = self.build_prompt(
            "generate_chat",
            {
                "agent": agent.name,
                "base_desc": self._base_desc(),
                "memory": memory,
                "address": f"{address[-2]}，{address[-1]}",
                "current_time": utils.get_timer().get_date("%H:%M"),
                "previous_context": prev_context,
                "current_context": curr_context,
                "another": other.name,
                "conversation": conversation,
            }
        )

        class generate_chat(BaseModel):
            res: str = Field(description="角色说出的对话内容，1到3句话")

        def _callback(response):
            response = response.strip()
            # 移除 "名字：" 前缀
            if response.startswith(agent.name + "：") or response.startswith(agent.name + ":"):
                response = response[len(agent.name) + 1:].strip()
            return response or failsafe

        failsafe = "嗯"
        return Result(prompt, _callback, failsafe, generate_chat)

    def prompt_generate_chat_check_repeat(self, agent, chats, content):
        conversation = "\n".join(["{}: {}".format(n, u) for n, u in chats])
        conversation = (
                conversation or "[对话尚未开始]"
        )

        class generate_chat_check_repeatResponse(BaseModel):
            res: bool = Field(description="新对话内容是否与历史记录重复，true 表示重复，false 表示不重复")

        prompt = self.build_prompt(
            "generate_chat_check_repeat",
            {
                "conversation": conversation,
                "content": f"{agent.name}: {content}",
                "agent": agent.name,
            }
        )

        def _callback(response):
            if isinstance(response, bool):
                return response
            return str(response).strip().lower() in ("true", "yes", "是", "1")

        failsafe = False
        return Result(prompt, _callback, failsafe, generate_chat_check_repeatResponse)

    def prompt_summarize_chats(self, chats):
        conversation = "\n".join(["{}: {}".format(n, u) for n, u in chats])

        prompt = self.build_prompt(
            "summarize_chats",
            {
                "conversation": conversation,
            }
        )

        class summarize_chatsResponse(BaseModel):
            res: str = Field(description="对话内容的简短摘要，一句话概括对话主题")

        def _callback(response):
            return response.strip()

        if len(chats) > 1:
            failsafe = "{} 和 {} 之间的普通对话".format(chats[0][0], chats[1][0])
        else:
            failsafe = "{} 说的话没有得到回应".format(chats[0][0])

        return Result(prompt, _callback, failsafe, summarize_chatsResponse)

    def prompt_reflect_focus(self, nodes, topk):
        prompt = self.build_prompt(
            "reflect_focus",
            {
                "reference": "\n".join(["{}. {}".format(idx, n.describe) for idx, n in enumerate(nodes)]),
                "number": topk,
            }
        )

        class reflect_focusResponse(BaseModel):
            res: List[str] = Field(description="需要深入思考的问题列表，每项为一个问题")

        def _callback(response):
            assert len(response) >= 1, "reflect_focus: empty list"
            return response

        failsafe = [
                "{} 是谁？".format(self.name),
                "{} 住在哪里？".format(self.name),
                "{} 今天要做什么？".format(self.name),
            ]
        return Result(prompt, _callback, failsafe, reflect_focusResponse)

    def prompt_reflect_insights(self, nodes, topk):
        prompt = self.build_prompt(
            "reflect_insights",
            {
                "reference": "\n".join(["{}. {}".format(idx, n.describe) for idx, n in enumerate(nodes)]),
                "number": topk,
            }
        )

        class reflect_insightsResponse(BaseModel):
            res: List[Tuple[str, str]] = Field(description="洞察列表，每项为 [洞察内容, 相关节点索引的逗号分隔字符串如'1,2,3'] 的元组")

        def _callback(response):  
            insights = []  
            for insight, node_ids_str in response:  
                # 将字符串"1,2,3"转换为节点ID列表  
                indices = [int(i.strip()) for i in node_ids_str.split(",")]  
                node_ids = [nodes[i].node_id for i in indices if i < len(nodes)]  
                insights.append([insight.strip(), node_ids])  
            return insights

        failsafe = [
                [
                    "{} 在考虑下一步该做什么".format(self.name),
                    [nodes[0].node_id],
                ]
            ]
        return Result(prompt, _callback, failsafe, reflect_insightsResponse)

    def prompt_reflect_chat_planing(self, chats):
        all_chats = "\n".join(["{}: {}".format(n, c) for n, c in chats])

        prompt = self.build_prompt(
            "reflect_chat_planing",
            {
                "conversation": all_chats,
                "agent": self.name,
            }
        )

        class reflect_chat_planingResponse(BaseModel):
            res: str = Field(description="从对话中提取的对角色计划的影响或启发，一句话描述")

        def _callback(response):
            return response.strip() or failsafe

        failsafe = f"{self.name} 进行了一次对话"
        return Result(prompt, _callback, failsafe, reflect_chat_planingResponse)

    def prompt_reflect_chat_memory(self, chats):
        all_chats = "\n".join(["{}: {}".format(n, c) for n, c in chats])

        prompt = self.build_prompt(
            "reflect_chat_memory",
            {
                "conversation": all_chats,
                "agent": self.name,
            }
        )
        class reflect_chat_memoryResponse(BaseModel):
            res: str = Field(description="从对话中提取的值得记忆的内容，一句话描述")

        def _callback(response):
            return response.strip() or failsafe

        failsafe = f"{self.name} 进行了一次对话"
        return Result(prompt, _callback, failsafe, reflect_chat_memoryResponse)

    def prompt_retrieve_plan(self, nodes):
        statements = [
            n.create.strftime("%Y-%m-%d %H:%M") + ": " + n.describe for n in nodes
        ]

        prompt = self.build_prompt(
            "retrieve_plan",
            {
                "description": "\n".join(statements),
                "agent": self.name,
                "date": utils.get_timer().get_date("%Y-%m-%d"),
            }
        )

        class retrieve_planResponse(BaseModel):
            res: List[str] = Field(description="从记忆中检索出的相关计划列表，每项为一条计划描述")

        def _callback(response):
            assert len(response) >= 1, "retrieve_plan: empty list"
            return response

        failsafe = [r.describe for r in random.choices(nodes, k=5)]
        return Result(prompt, _callback, failsafe, retrieve_planResponse)

    def prompt_retrieve_thought(self, nodes):
        statements = [
            n.create.strftime("%Y-%m-%d %H:%M") + "：" + n.describe for n in nodes
        ]

        prompt = self.build_prompt(
            "retrieve_thought",
            {
                "description": "\n".join(statements),
                "agent": self.name,
            }
        )

        class retrieve_thoughtResponse(BaseModel):
            res: str = Field(description="从记忆中检索出的相关思考内容，一句话总结")

        def _callback(response):
            return response.strip() or failsafe

        failsafe = "{} 应该遵循昨天的日程".format(self.name)
        return Result(prompt, _callback, failsafe, retrieve_thoughtResponse)

    def prompt_retrieve_currently(self, plan_note, thought_note):
        time_stamp = (
            utils.get_timer().get_date() - datetime.timedelta(days=1)
        ).strftime("%Y-%m-%d")

        prompt = self.build_prompt(
            "retrieve_currently",
            {
                "agent": self.name,
                "time": time_stamp,
                "currently": self.currently,
                "plan": ". ".join(plan_note),
                "thought": thought_note,
                "current_time": utils.get_timer().get_date("%Y-%m-%d"),
            }
        )

        class retrieve_currentlyResponse(BaseModel):
            res: str = Field(description="角色当前状态的更新描述，基于过去的计划和思考")

        def _callback(response):
            return response.strip() or failsafe

        failsafe = self.currently

        return Result(prompt, _callback, failsafe, retrieve_currentlyResponse)
