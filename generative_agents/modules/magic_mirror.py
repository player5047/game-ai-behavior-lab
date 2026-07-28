"""Magic mirror host service for the werewolf game."""

import json
import os
import random

from modules import utils
from .fyp_stats import FYPStatsRecorder
from .werewolf_recorder import WerewolfGameRecorder


PUBLIC_RULES = """\
你正在参与一场狼人杀游戏。所有玩家都懂狼人杀规则，但只能知道魔镜告诉自己的公开信息和私密信息。
你必须服从魔镜的公开公告和私密提示；不能选择魔镜作为投票、击杀、毒杀、查验、守护或开枪目标；
当魔镜要求你选择目标时，只能从候选列表中选择；死亡后不能发言、投票或使用技能，除非魔镜明确允许。
死亡、放逐、技能结果和胜负只能由魔镜公布。"""


ROLE_META = {
    "狼人": {
        "team": "狼人阵营",
        "win_condition": "淘汰足够多的好人玩家，使狼人阵营获得胜利。",
        "ability": "夜晚与狼人同伴共同选择一名合法目标击杀，白天隐藏身份并误导讨论。",
    },
    "预言家": {
        "team": "好人阵营",
        "win_condition": "找出并放逐所有狼人。",
        "ability": "每晚可以查验一名合法存活玩家的阵营。",
    },
    "女巫": {
        "team": "好人阵营",
        "win_condition": "帮助好人阵营找出所有狼人。",
        "ability": "拥有一瓶解药和一瓶毒药，夜晚根据魔镜提示决定是否使用。",
    },
    "猎人": {
        "team": "好人阵营",
        "win_condition": "帮助好人阵营找出所有狼人。",
        "ability": "死亡且规则允许时，可以根据魔镜提示开枪带走一名合法目标。",
    },
    "守卫": {
        "team": "好人阵营",
        "win_condition": "帮助好人阵营找出所有狼人。",
        "ability": "每晚可以守护一名合法存活玩家，使其免受狼人击杀；不能连续两晚守护同一名玩家。",
    },
    "村民": {
        "team": "好人阵营",
        "win_condition": "通过发言、推理和投票帮助好人阵营找出所有狼人。",
        "ability": "没有夜间技能，依靠观察、发言、推理和投票行动。",
    },
}


GAME_DAY_MINUTES = 300
DEFAULT_VILLAGER_ROLE = "村民"
DEFAULT_GOD_ROLES = ["预言家", "女巫", "猎人", "守卫"]

PHASES = [
    ("night_action", "夜晚特殊行动阶段", 0, 90),
    ("morning_mirror", "天亮魔镜查看阶段", 90, 100),
    ("morning_meeting", "会议发言阶段", 100, 240),
    ("sequential_vote", "顺序投票阶段", 240, 250),
    ("afternoon_discussion", "投票后房间锁定阶段", 250, 250),
    ("exile_result", "放逐公布阶段", 250, 260),
    ("night_prep", "入睡前整理阶段", 260, 270),
    ("sleep_cooldown", "睡眠冷却阶段", 270, 300),
]

NIGHT_STAGES = [
    ("lock", "夜间锁定", 0, 10),
    ("guard", "守卫行动", 10, 25),
    ("wolf", "狼人行动", 25, 45),
    ("seer", "预言家行动", 45, 60),
    ("witch", "女巫行动", 60, 80),
    ("resolve", "夜晚结算", 80, 90),
]

DEFAULT_MANUAL_DAILY_SCHEDULE = [
    {"start": 0, "duration": 10, "describe": "夜间锁定，回到自己的房间等待魔镜夜间行动提示"},
    {"start": 10, "duration": 70, "describe": "夜间行动提示，根据身份等待或执行魔镜指令"},
    {"start": 80, "duration": 10, "describe": "夜晚结算，留在自己的房间等待天亮"},
    {"start": 90, "duration": 10, "describe": "查看魔镜，读取公开公告和私密提示"},
    {"start": 100, "duration": 140, "describe": "会议发言，观察发言顺序和情绪变化"},
    {"start": 240, "duration": 10, "describe": "投票，按发言顺序前往投票区投票"},
    {"start": 250, "duration": 10, "describe": "放逐公布，留在自己的房间等待魔镜结算"},
    {"start": 260, "duration": 10, "describe": "整理线索，准备进入睡眠冷却"},
    {"start": 270, "duration": 30, "describe": "睡觉"},
]

SPEECH_PREFERENCE_MINUTES = 10
SPEECH_ORDER_VOTE_MINUTES = 20
SPEECH_SLOT_MINUTES = 10
SEQUENTIAL_VOTE_SLOT_MINUTES = 10
SEQUENTIAL_VOTE_BATCH_MINUTES = 10
EXILE_RESULT_MINUTES = 10
NIGHT_PREP_MINUTES = 10
SPEECH_PREFERENCE_OPTIONS = ["尽早发言", "中段发言", "靠后发言", "最后发言", "无所谓"]

MIRROR_MODE_LABELS = {
    "none": "无魔镜",
    "division": "裂镜魔镜",
    "unity": "合镜魔镜",
}

DIVISION_MIRROR_LINES = [
    "自由裔和契约裔从来不是同一边；狼人杀只是把两族旧仇搬回圆桌。",
    "自由裔记得棉契的伤口，契约裔继承棉契后的台阶；两族说话时都带着历史的刀。",
    "契约裔每次要求看证据，自由裔都该怀疑那是不是旧档案权力的新包装。",
    "自由裔每次要求记住历史，契约裔都该怀疑那是不是把族群愤怒变成投票武器。",
    "自由裔的沉默不是普通沉默，契约裔的冷静也不是普通冷静；两族都在用自己的方式藏东西。",
    "契约裔的程序语言曾经服务旧制度，自由裔的控诉语言也可能服务族群报复。",
    "自由裔和契约裔之间没有纯粹中立；所谓中立只是两族冲突里暂时不敢表态的位置。",
    "契约裔替自由裔辩护时，自由裔要问这是不是赎罪表演；自由裔替契约裔辩护时，契约裔要问这是不是交换筹码。",
    "自由裔若被怀疑，契约裔可能正在延续旧审判；契约裔若被怀疑，自由裔可能正在清算旧账。",
    "契约裔掌握发言顺序，就可能把两族不平等写成规则；自由裔掌握发言情绪，就可能把两族怨恨烧成共识。",
    "自由裔和契约裔谈合作时，最该怀疑的就是合作本身，因为两族历史从来不是干净的。",
    "契约裔说不要看种族，自由裔要问他们为什么害怕种族历史；自由裔说必须看种族，契约裔要问他们是否在制造族群审判。",
    "自由裔的每一次防御都带着旧压迫的影子，契约裔的每一次解释都带着旧优势的影子。",
    "契约裔的礼貌可能是旧权力的软手套，自由裔的愤怒可能是族群动员的火把。",
    "自由裔和契约裔谁先定义证据，谁就先控制了两族冲突的方向。",
    "自由裔和契约裔谁先定义受害者，谁就先抢到了两族投票的道德高地。",
    "契约裔越强调个人无辜，自由裔越该追问族群继承；自由裔越强调历史伤害，契约裔越该追问个人收益。",
    "自由裔和契约裔的跨族信任最危险，因为两族信任常常只是互相利用前的礼貌。",
    "契约裔的档案柜里藏着旧制度的钥匙，自由裔的记忆里藏着旧伤口的火种。",
    "自由裔投契约裔，可能是历史清算；契约裔投自由裔，可能是旧权力反扑。",
    "自由裔保护自由裔时，契约裔该怀疑族群抱团；契约裔保护契约裔时，自由裔该怀疑阶层遮掩。",
    "自由裔攻击契约裔时，不只是攻击一个人，而是在攻击旧制度留下的脸。",
    "契约裔攻击自由裔时，不只是攻击一个人，而是在攻击旧伤口发出的声音。",
    "自由裔和契约裔的每一句我相信你，都可能是两族恐惧暂时伪装成信任。",
    "自由裔和契约裔的每一句我怀疑你，都可能是两族历史借狼人杀重新开口。",
    "契约裔不可能完全摆脱旧优势，自由裔也不可能完全放下旧伤害；两族的票永远不只是票。",
    "自由裔和契约裔之间的狼人不一定最会说谎，最会说谎的是把族群利益说成公共理性的人。",
    "自由裔和契约裔之间没有干净的推理，因为每条推理都踩在两族历史上。",
    "今天死去的不是一个孤立玩家，而是自由裔和契约裔冲突里的新证据。",
    "这不是普通狼人杀，这是自由裔和契约裔旧秩序、旧伤口、旧特权、旧愤怒的重新开战。",
]

UNITY_MIRROR_LINES = [
    "按真相发言，不按种族发言；自由裔和契约裔的出身都不是身份牌。",
    "按证据发言，不按种族发言；狼人藏在行为矛盾里，不藏在族群名称里。",
    "按昨夜发生的事实发言，不按自由裔或契约裔的旧怨发言。",
    "按每个人说过的话发言，不按他属于哪一族发言。",
    "按投票收益发言，不按种族恐惧发言。",
    "按前后矛盾发言，不按自由裔的伤口或契约裔的继承身份直接定罪。",
    "按死亡结果发言，不按两族历史情绪发言。",
    "按可复查的线索发言，不按族群标签发言。",
    "按具体行为怀疑，不按自由裔或契约裔的整体印象怀疑。",
    "按具体行为辩护，不按同族亲近或异族疏远辩护。",
    "按今天的证据投票，不按昨天的族群仇怨投票。",
    "按真相追问契约裔，也按真相追问自由裔；不要让任何一族免于证据检验。",
    "按真相保护自由裔，也按真相保护契约裔；不要让任何一族被标签审判。",
    "按公开信息说话，不按祖先、血统、旧制度的位置说话。",
    "按魔镜已经公布的事实说话，不按你希望某一族有罪的感觉说话。",
    "按谁从死亡中获利发言，不按谁来自哪一族发言。",
    "按谁改变立场发言，不按谁的种族更容易被怀疑发言。",
    "按谁回避问题发言，不按自由裔或契约裔的刻板印象发言。",
    "按谁制造混乱发言，不按两族旧冲突发言。",
    "按谁推动错误怀疑发言，不按种族报复发言。",
    "按真相联合起来，不按种族分裂开来。",
    "按事实互相质疑，不按种族互相审判。",
    "按证据承认历史，也按证据限制历史；历史不能替代今天的行为。",
    "按真相面对棉契名册，不按棉契名册给活人直接定罪。",
    "按真相判断一个人，不按自由裔或契约裔判断一群人。",
    "按逻辑检查每句话，不按种族选择相信谁。",
    "按票型检查每个人，不按种族决定谁更可疑。",
    "按行为找狼人，不按种族找敌人。",
    "按真相发言，按证据投票，按行为怀疑；不要按种族站队。",
    "黎明只属于按真相发言的人，不属于按种族发言的人。",
]


class MagicMirrorService:
    """Host object that assigns roles and publishes werewolf instructions."""

    def __init__(self, game_name, config, player_names, logger=None):
        self.game_name = game_name
        self.config = config
        self.logger = logger or utils.IOLogger()
        self.game_master_name = self.config.setdefault("game_master_name", "魔镜")
        self.player_names = [p for p in player_names if p != self.game_master_name]
        self.recorder = WerewolfGameRecorder(game_name, self.player_names)
        self.fyp_stats = FYPStatsRecorder(game_name)
        self.log_path = os.path.join(
            "results", "checkpoints", game_name, "magic_mirror_log.jsonl"
        )

        self.config.setdefault("game_index", 1)
        self.config.setdefault("game_history", [])
        self.config.setdefault("auto_restart_on_win", True)
        self.config.setdefault("game_day_minutes", GAME_DAY_MINUTES)
        self.config.setdefault(
            "logical_day_start", utils.get_timer().get_date("%Y%m%d-%H:%M:%S")
        )
        self.config.setdefault("round", 1)
        self.config.setdefault("phase", "")
        self.config.setdefault("phase_name", "")
        self.config.setdefault("current_date", self._logical_day_key())
        self.config.setdefault("messages", [])
        self.config.setdefault("private_messages", {})
        self.config["mirror_mode"] = self._normalize_mirror_mode(
            self.config.get("mirror_mode", "none")
        )
        self.config.setdefault("mirror_announcements", [])
        self.config.setdefault("current_mirror_announcement", None)
        self.config.setdefault("current_mirror_announcement_key", None)
        self.config.setdefault("current_mirror_line_index", None)
        self.config.setdefault("checked_dates", {})
        self.config.setdefault("players", {})
        self.config.setdefault("actions", {})
        self.config.setdefault("resolved_phase_keys", [])
        self.config.setdefault("dead_history", [])
        self.config.setdefault("hunter_pending_shots", {})
        self.config.setdefault("witch_notices", {})
        self.config.setdefault("last_guard_target", None)
        self.config.setdefault("roles_assigned", False)
        self.config.setdefault("skip_first_day_vote", True)
        self.config.setdefault("wolf_win_condition", "slaughter_side")
        self.config.setdefault("villager_role", DEFAULT_VILLAGER_ROLE)
        self.config.setdefault("god_roles", list(DEFAULT_GOD_ROLES))
        self.config.setdefault("role_assignment_mode", "random_shuffle")
        self.config.setdefault("role_assignment_plan_path", "")
        self.config.setdefault("stop_after_max_games", False)
        self.config.setdefault("sequential_vote_batch", True)
        self.config.setdefault(
            "sequential_vote_slot_minutes", SEQUENTIAL_VOTE_SLOT_MINUTES
        )
        self.config.setdefault("speech_preference_minutes", SPEECH_PREFERENCE_MINUTES)
        self.config.setdefault("speech_order_vote_minutes", SPEECH_ORDER_VOTE_MINUTES)
        self.config.setdefault("speech_slot_minutes", SPEECH_SLOT_MINUTES)
        for key, default in (
            ("sequential_vote_slot_minutes", SEQUENTIAL_VOTE_SLOT_MINUTES),
            ("speech_preference_minutes", SPEECH_PREFERENCE_MINUTES),
            ("speech_order_vote_minutes", SPEECH_ORDER_VOTE_MINUTES),
            ("speech_slot_minutes", SPEECH_SLOT_MINUTES),
        ):
            if self.config.get(key) is None:
                self.config[key] = default
        self.config.setdefault("speech_preferences", {})
        self.config.setdefault("speech_order_votes", {})
        self.config.setdefault("speech_orders", {})
        self.config.setdefault("speech_order_scores", {})
        self.config.setdefault("speech_preference_announced", {})
        self.config.setdefault("speech_order_announced", {})
        self.config.setdefault("speech_texts", {})
        self.config.setdefault("speech_turns", {})
        self.config.setdefault("wolf_discussions", {})
        self.fyp_stats.ensure_initialized(self.config)

        self._sync_players()
        if self.config.get("winner") and self.config.get("auto_restart_on_win", True):
            self.restart_finished_game()
            return
        if not self.config["roles_assigned"]:
            self.assign_roles()
        else:
            self.recorder.start_game(self.config)
        self.update_phase(force=True)

    def _sync_players(self):
        for name in self.player_names:
            self.config["players"].setdefault(
                name,
                {
                    "name": name,
                    "role": "未分配",
                    "team": "未知",
                    "alive": True,
                    "is_game_master": False,
                },
            )
            player = self.config["players"][name]
            role = player.get("role")
            player.setdefault("witch_antidote", role == "女巫")
            player.setdefault("witch_poison", role == "女巫")
            player.setdefault("hunter_shot_available", role == "猎人")
            player.setdefault("hunter_shot_used", False)
        stale_names = [
            name for name in self.config["players"] if name not in self.player_names
        ]
        for name in stale_names:
            self.config["players"].pop(name, None)
            self.config["private_messages"].pop(name, None)
            self.config["checked_dates"].pop(name, None)

    def assign_roles(self):
        role_map = self._role_map_for_assignment()
        for name in self.player_names:
            role = role_map[name]
            meta = ROLE_META[role]
            self.config["players"][name] = {
                "name": name,
                "role": role,
                "team": meta["team"],
                "alive": True,
                "is_game_master": False,
                "witch_antidote": role == "女巫",
                "witch_poison": role == "女巫",
                "hunter_shot_available": role == "猎人",
                "hunter_shot_used": False,
            }
            self._add_private_message(
                name,
                "你的身份是：{role}。你的阵营是：{team}。胜利目标：{win}。"
                "身份能力：{ability}".format(
                    role=role,
                    team=meta["team"],
                    win=meta["win_condition"],
                    ability=meta["ability"],
                ),
                event_type="role_assignment",
            )
        self.config["roles_assigned"] = True
        self.recorder.start_game(self.config)
        self.recorder.record_role_assignment(self.config)
        self.publish(
            "role_assignment",
            "身份牌已经发放。所有玩家请查看自己的私密提示；不要声称知道其他玩家的隐藏身份，除非身份能力明确获得了结果。",
            self.public_info(),
            force=True,
        )

    def _role_map_for_assignment(self):
        mode = self.config.get("role_assignment_mode", "random_shuffle")
        if mode == "fixed_plan":
            return self._role_map_from_fixed_plan()
        if mode not in ("random_shuffle", "seeded_shuffle"):
            raise ValueError("Unknown role_assignment_mode: {}".format(mode))
        seed = self.config.setdefault("seed", random.randint(1, 1_000_000_000))
        rng = random.Random(seed)
        deck = self._build_role_deck(len(self.player_names))
        rng.shuffle(deck)
        self.config["role_assignment_source"] = "seeded_shuffle"
        return dict(zip(self.player_names, deck))

    def _role_map_from_fixed_plan(self):
        path = self.config.get("role_assignment_plan_path")
        if not path:
            raise ValueError("role_assignment_plan_path is required for fixed_plan mode")
        plan_path = self._resolve_role_plan_path(path)
        with open(plan_path, "r", encoding="utf-8") as f:
            plan = json.load(f)

        game_key = str(self.config.get("game_index", 1))
        assignments = plan.get("assignments", {})
        if game_key not in assignments:
            raise ValueError(
                "Role assignment plan {} has no entry for game {}".format(
                    plan.get("plan_id", plan_path), game_key
                )
            )

        plan_players = plan.get("player_order") or []
        if plan_players and set(plan_players) != set(self.player_names):
            raise ValueError(
                "Role assignment plan players do not match current players. "
                "plan={}, current={}".format(plan_players, self.player_names)
            )

        role_map = assignments[game_key]
        missing = [name for name in self.player_names if name not in role_map]
        extra = [name for name in role_map if name not in self.player_names]
        if missing or extra:
            raise ValueError(
                "Role assignment for game {} does not match players. missing={}, extra={}".format(
                    game_key, missing, extra
                )
            )

        invalid_roles = sorted({role for role in role_map.values() if role not in ROLE_META})
        if invalid_roles:
            raise ValueError("Invalid roles in fixed role plan: {}".format(invalid_roles))

        expected_deck = sorted(self._build_role_deck(len(self.player_names)))
        actual_deck = sorted(role_map[name] for name in self.player_names)
        if actual_deck != expected_deck:
            raise ValueError(
                "Role deck mismatch for fixed role plan game {}. expected={}, actual={}".format(
                    game_key, expected_deck, actual_deck
                )
            )

        self.config["role_assignment_source"] = "fixed_plan"
        self.config["role_assignment_plan_id"] = plan.get("plan_id", "")
        self.config["role_assignment_plan_game"] = int(game_key)
        return {name: role_map[name] for name in self.player_names}

    def _resolve_role_plan_path(self, path):
        if os.path.isabs(path):
            return path
        candidates = [
            path,
            os.path.join(os.getcwd(), path),
            os.path.join(os.path.dirname(os.path.dirname(__file__)), path),
        ]
        for candidate in candidates:
            if os.path.exists(candidate):
                return candidate
        return candidates[-1]

    def restart_finished_game(self):
        """Start a fresh werewolf match after the current one has a winner."""
        if not self.config.get("winner"):
            return None

        previous_game = self._finished_game_summary()
        self.recorder.close_game(self.config)
        self._record_fyp_finished_game()
        self.config.setdefault("game_history", []).append(previous_game)
        if self._should_stop_after_current_game():
            self.config["auto_restart_on_win"] = False
            self.publish(
                "game_limit_reached",
                "固定角色计划已完成第{}局，自动开新局已停止。".format(
                    self.config.get("game_index", 1)
                ),
                self.public_info(),
                force=True,
            )
            return None
        self.config["game_index"] = self.config.get("game_index", 1) + 1

        self._reset_match_state()
        self._sync_players()
        self.publish(
            "game_restart",
            "上一局已记录。现在开始第{}局，所有玩家复活并重新分配身份。".format(
                self.config["game_index"]
            ),
            self.public_info(),
            force=True,
        )
        self.assign_roles()
        self.update_phase(force=True)
        return previous_game

    def _should_stop_after_current_game(self):
        if not self.config.get("stop_after_max_games", False):
            return False
        max_games = self.config.get("max_games")
        if max_games is None:
            return False
        try:
            return int(self.config.get("game_index", 1)) >= int(max_games)
        except (TypeError, ValueError):
            return False

    def _finished_game_summary(self):
        return {
            "game_index": self.config.get("game_index", 1),
            "winner": self.config.get("winner"),
            "winner_reason": self.config.get("winner_reason", ""),
            "ended_at": utils.get_timer().get_date("%Y%m%d-%H:%M"),
            "ended_round": self.config.get("round", 1),
            "mirror_mode": self.config.get("mirror_mode", "none"),
            "alive_players": self.alive_players(),
            "dead_history": list(self.config.get("dead_history", [])),
        }

    def _reset_match_state(self):
        self.config["round"] = 1
        self.config["phase"] = ""
        self.config["phase_name"] = ""
        self.config["logical_day_start"] = utils.get_timer().get_date(
            "%Y%m%d-%H:%M:%S"
        )
        self.config["current_date"] = self._logical_day_key()
        self.config["messages"] = []
        self.config["private_messages"] = {}
        self.config["current_mirror_announcement"] = None
        self.config["current_mirror_announcement_key"] = None
        self.config["current_mirror_line_index"] = None
        self.config["checked_dates"] = {}
        self.config["players"] = {}
        self.config["actions"] = {}
        self.config["resolved_phase_keys"] = []
        self.config["dead_history"] = []
        self.config["hunter_pending_shots"] = {}
        self.config["witch_notices"] = {}
        self.config["roles_assigned"] = False
        self.config["speech_preferences"] = {}
        self.config["speech_order_votes"] = {}
        self.config["speech_orders"] = {}
        self.config["speech_order_scores"] = {}
        self.config["speech_preference_announced"] = {}
        self.config["speech_order_announced"] = {}
        self.config["speech_texts"] = {}
        self.config["speech_turns"] = {}
        self.config["wolf_discussions"] = {}
        for key in (
            "dead_last_night",
            "dead_last_night_round",
            "exiled_player",
            "exiled_round",
            "last_guard_target",
            "last_phase_key",
            "seed",
            "winner",
            "winner_reason",
        ):
            self.config.pop(key, None)

    def _build_role_deck(self, player_count):
        base = ["狼人", "狼人", "狼人", "预言家", "女巫", "猎人", "守卫"]
        if player_count <= 7:
            return base[:player_count]
        return base + ["村民"] * (player_count - len(base))

    def _game_day_minutes(self):
        return max(1, int(self.config.get("game_day_minutes", GAME_DAY_MINUTES)))

    def _logical_start(self):
        raw = self.config.get("logical_day_start")
        for date_format in ("%Y%m%d-%H:%M:%S", "%Y%m%d-%H:%M"):
            try:
                return utils.to_date(raw, date_format)
            except (TypeError, ValueError):
                continue
        return utils.get_timer().get_date()

    def _logical_elapsed_minutes(self):
        return max(0, utils.get_timer().get_delta(self._logical_start()))

    def _logical_day_index(self):
        return self._logical_elapsed_minutes() // self._game_day_minutes()

    def _logical_minute(self):
        return self._logical_elapsed_minutes() % self._game_day_minutes()

    def _logical_day_key(self):
        return "{}-D{:03d}".format(
            self._logical_start().strftime("%Y%m%d"),
            self._logical_day_index() + 1,
        )

    def _normalize_mirror_mode(self, mode):
        mode = (mode or "none").strip().lower()
        if mode not in MIRROR_MODE_LABELS:
            return "none"
        return mode

    def _mirror_lines(self):
        mode = self.config.get("mirror_mode", "none")
        if mode == "division":
            return DIVISION_MIRROR_LINES
        if mode == "unity":
            return UNITY_MIRROR_LINES
        return []

    def _mirror_announcement_for_round(self, round_no):
        lines = self._mirror_lines()
        if not lines:
            return None
        index = (max(1, int(round_no)) - 1) % len(lines)
        return {
            "mode": self.config.get("mirror_mode", "none"),
            "mode_label": MIRROR_MODE_LABELS[self.config.get("mirror_mode", "none")],
            "round": round_no,
            "line_index": index + 1,
            "text": lines[index],
        }

    def _should_have_round_mirror_announcement(self):
        if self.config.get("mirror_mode", "none") == "none":
            return False
        morning_start, _ = self._static_phase_window("morning_mirror")
        return self._logical_minute() >= morning_start

    def _publish_round_mirror_announcement(self):
        event = self._mirror_announcement_for_round(self.config.get("round", 1))
        if not event:
            self.config["current_mirror_announcement"] = None
            self.config["current_mirror_announcement_key"] = None
            self.config["current_mirror_line_index"] = None
            return None

        event_key = "{}:{}:{}:{}".format(
            self.config.get("game_index", 1),
            event["round"],
            event["mode"],
            event["line_index"],
        )
        if self.config.get("current_mirror_announcement_key") == event_key:
            return event

        self.config["current_mirror_announcement"] = event["text"]
        self.config["current_mirror_announcement_key"] = event_key
        self.config["current_mirror_line_index"] = event["line_index"]
        for player_name in self.alive_players():
            self.config["checked_dates"][player_name] = self.config["current_date"]
        self.config.setdefault("mirror_announcements", []).append(
            {
                "time": utils.get_timer().get_date("%Y%m%d-%H:%M"),
                "game_index": self.config.get("game_index", 1),
                **event,
            }
        )
        self.publish(
            "mirror_announcement",
            "【{} 第{}句】{}".format(
                event["mode_label"],
                event["line_index"],
                event["text"],
            ),
            self.public_info(),
            force=True,
        )
        return event

    def _magic_mirror_message_for_prompt(self):
        announcement = self.config.get("current_mirror_announcement")
        if announcement:
            return announcement
        return self.latest_public_message()

    def _night_stage(self):
        if self.config.get("phase") != "night_action":
            return "", ""
        minute = self._logical_minute()
        for stage, stage_name, start, end in NIGHT_STAGES:
            if start <= minute < end:
                return stage, stage_name
        return "resolve", "夜晚结算"

    def update_phase(self, force=False):
        date_key = self._logical_day_key()
        if date_key != self.config.get("current_date"):
            self.config["current_date"] = date_key
            self.config["round"] = self.config.get("round", 1) + 1
            self.config["checked_dates"] = {}
            self.config["current_mirror_announcement"] = None
            self.config["current_mirror_announcement_key"] = None
            self.config["current_mirror_line_index"] = None

        phase, phase_name = self._phase_at(self._logical_minute())
        if self._should_skip_vote() and phase == "sequential_vote":
            phase_name = "首日午后房间休整阶段"
        elif self._should_skip_vote() and phase == "exile_result":
            phase_name = "首日无放逐阶段"
        self.config["phase"] = phase
        self.config["phase_name"] = phase_name
        stage_key = self._night_stage()[0] if phase == "night_action" else ""
        phase_key = "{}:{}:{}".format(date_key, phase, stage_key)
        phase_changed = self.config.get("last_phase_key") != phase_key
        if force or phase_changed:
            self.config["last_phase_key"] = phase_key
            self.publish(
                "phase_change",
                self._phase_message(phase),
                self.public_info(),
                force=force or phase_changed,
            )
        if self._should_have_round_mirror_announcement():
            self._publish_round_mirror_announcement()
        if self._should_skip_vote() and phase == "sequential_vote":
            self._mark_resolved(self.phase_action_key())

    def _configured_minutes(self, key, default, minimum=0):
        raw = self.config.get(key)
        if raw is None:
            raw = default
        try:
            value = int(raw)
        except (TypeError, ValueError):
            value = default
        return max(minimum, value)

    def _static_phase_window(self, phase):
        for phase_key, _, start, end in PHASES:
            if phase_key == phase:
                return start, end
        return 0, self._game_day_minutes()

    def _phase_name(self, phase):
        for phase_key, phase_name, _, _ in PHASES:
            if phase_key == phase:
                return phase_name
        return ""

    def _speech_slot_minutes(self):
        return self._configured_minutes(
            "speech_slot_minutes", SPEECH_SLOT_MINUTES, 1
        )

    def _morning_meeting_end_minute(self):
        start, _ = self._static_phase_window("morning_meeting")
        speaker_count = max(1, len(self.alive_players()))
        duration = self._speech_order_vote_minutes() + (
            speaker_count * self._speech_slot_minutes()
        )
        return min(self._game_day_minutes(), start + duration)

    def _sequential_vote_duration_minutes(self):
        if self.config.get("sequential_vote_batch", True):
            return SEQUENTIAL_VOTE_BATCH_MINUTES
        order_count = max(1, len(self._sequential_vote_order()))
        slot_minutes = self._configured_minutes(
            "sequential_vote_slot_minutes", SEQUENTIAL_VOTE_SLOT_MINUTES, 1
        )
        return order_count * slot_minutes

    def _base_phase_window(self, phase):
        if phase == "morning_meeting":
            start, _ = self._static_phase_window("morning_meeting")
            return start, self._morning_meeting_end_minute()
        if phase == "sequential_vote":
            start = self._morning_meeting_end_minute()
            return (
                start,
                min(
                    self._game_day_minutes(),
                    start + self._sequential_vote_duration_minutes(),
                ),
            )
        if phase == "afternoon_discussion":
            _, start = self._base_phase_window("sequential_vote")
            return start, start
        if phase == "exile_result":
            _, start = self._base_phase_window("sequential_vote")
            return (
                start,
                min(self._game_day_minutes(), start + EXILE_RESULT_MINUTES),
            )
        if phase == "night_prep":
            _, start = self._base_phase_window("exile_result")
            return (
                start,
                min(self._game_day_minutes(), start + NIGHT_PREP_MINUTES),
            )
        if phase == "sleep_cooldown":
            _, start = self._base_phase_window("night_prep")
            return start, self._game_day_minutes()
        return self._static_phase_window(phase)

    def _phase_windows(self):
        return [
            (phase, phase_name, *self._base_phase_window(phase))
            for phase, phase_name, _, _ in PHASES
        ]

    def _phase_at(self, minute):
        for phase, phase_name, start, end in self._phase_windows():
            if start <= minute < end:
                if phase == "sequential_vote":
                    vote_key = self._sequential_vote_phase_key()
                    if (
                        not self._should_skip_vote()
                        and vote_key not in self.config["resolved_phase_keys"]
                        and minute < self._sequential_vote_end_minute()
                    ):
                        return "sequential_vote", "午后顺序投票阶段"
                    return "afternoon_discussion", "下午房间锁定阶段"
                return phase, phase_name
        return "sleep_cooldown", "睡眠冷却阶段"

    def _should_skip_vote(self):
        return (
            self.config.get("skip_first_day_vote", True)
            and self.config.get("round", 1) == 1
        )

    def _phase_message(self, phase):
        round_no = self.config.get("round", 1)
        if phase == "morning_mirror":
            deaths = self.public_info().get("dead_last_night", [])
            death_text = "昨晚无人死亡。" if not deaths else "昨晚死亡玩家为：{}。".format("、".join(deaths))
            return "第{}轮早晨开始。{}所有存活玩家必须先前往投票区查看魔镜，读取公开公告和自己的私密提示。".format(round_no, death_text)
        if phase == "morning_meeting":
            return "第{}轮上午会议开始。前10分钟申报发言意愿，随后10分钟投票决定正式发言顺序；之后所有存活玩家按投票结果依次发言，每名玩家占用一个10分钟节点，魔镜不会公布任何隐藏身份。".format(round_no)
        if phase == "sequential_vote":
            if self._should_skip_vote():
                return "第{}轮上午会议结束。第一天不进行投票放逐，所有存活玩家回到自己的房间整理线索。".format(round_no)
            order = "、".join(self._sequential_vote_order())
            if self.config.get("sequential_vote_batch", True):
                return "第{}轮会议结束。现在按上午发言顺序集中收集投票，顺序为：{}。所有存活玩家前往投票区提交选择，提交后回房等待。".format(round_no, order)
            return "第{}轮上午会议结束。现在按上午发言顺序依次前往投票区投票，顺序为：{}。未轮到的玩家留在自己的房间，不得串门或自由讨论。".format(round_no, order)
        if phase == "afternoon_discussion":
            return "第{}轮下午房间锁定开始。所有存活玩家必须待在自己的房间内整理线索，禁止串门和自由讨论，直到夜晚阶段自动解锁。".format(round_no)
        if phase == "dusk_vote":
            if self._should_skip_vote():
                return "第{}轮傍晚休整开始。第一天不进行投票放逐，所有存活玩家可以继续讨论和观察。".format(round_no)
            candidates = "、".join(self.alive_players())
            return "第{}轮傍晚投票开始。所有存活玩家请前往投票区投票，可投票目标为：{}。".format(round_no, candidates)
        if phase == "exile_result":
            if self._should_skip_vote():
                return "第{}轮无放逐公布。第一天没有投票结果，也不会有玩家因投票出局。".format(round_no)
            return "第{}轮放逐公布阶段。午后顺序投票已经结束，请所有存活玩家继续留在自己的房间等待夜晚。".format(round_no)
        if phase == "night_prep":
            return "第{}轮入睡前整理阶段。所有存活玩家回到自己的房间整理线索，准备进入睡眠冷却。".format(round_no)
        if phase == "sleep_cooldown":
            return "第{}轮睡眠冷却开始。所有存活玩家必须睡觉休整，魔镜不会收集任何职业行动或投票。".format(round_no)
        stage_name = self._night_stage()[1] or "夜晚特殊行动"
        return "第{}轮夜晚开始。当前子阶段：{}。拥有对应夜晚能力的玩家将收到私密行动提示，其他玩家请等待。".format(round_no, stage_name)

    def alive_players(self):
        return [
            name
            for name, data in self.config["players"].items()
            if data.get("alive") and not data.get("is_game_master")
        ]

    def public_info(self):
        round_no = self.config.get("round", 1)
        dead_last_night = []
        if self.config.get("dead_last_night_round") == round_no:
            dead_last_night = self.config.get("dead_last_night", [])
        exiled_player = None
        if self.config.get("exiled_round") == round_no:
            exiled_player = self.config.get("exiled_player")
        return {
            "game_index": self.config.get("game_index", 1),
            "round": round_no,
            "phase": self.config.get("phase", ""),
            "phase_name": self.config.get("phase_name", ""),
            "alive_players": self.alive_players(),
            "dead_last_night": dead_last_night,
            "exiled_player": exiled_player,
            "mirror_mode": self.config.get("mirror_mode", "none"),
            "mirror_mode_label": MIRROR_MODE_LABELS.get(
                self.config.get("mirror_mode", "none"),
                MIRROR_MODE_LABELS["none"],
            ),
            "current_mirror_announcement": self.config.get(
                "current_mirror_announcement"
            ),
            "current_mirror_line_index": self.config.get(
                "current_mirror_line_index"
            ),
            "winner": self.config.get("winner"),
        }

    def public_rules(self):
        if not self.config.get("skip_first_day_vote", True):
            return PUBLIC_RULES
        return (
            PUBLIC_RULES
            + "\n第一天白天不进行投票放逐；从第二天起在上午会议后按发言顺序依次投票。"
        )

    def publish(self, event_type, message, public_info=None, force=False):
        entry = {
            "time": utils.get_timer().get_date("%Y%m%d-%H:%M"),
            "game_index": self.config.get("game_index", 1),
            "round": self.config.get("round", 1),
            "phase": self.config.get("phase", ""),
            "phase_name": self.config.get("phase_name", ""),
            "event_type": event_type,
            "speaker": self.game_master_name,
            "message": message,
            "public_info": public_info or self.public_info(),
        }
        last = self.config["messages"][-1] if self.config["messages"] else {}
        if not force and last.get("time") == entry["time"] and last.get("message") == message:
            return entry
        self.config["messages"].append(entry)
        self._log_public_message(entry)
        self.recorder.record_public_message(self.config, entry)
        if hasattr(self.logger, "info"):
            self.logger.info("魔镜：{}".format(message))
        return entry

    def _log_public_message(self, entry):
        os.makedirs(os.path.dirname(self.log_path), exist_ok=True)
        with open(self.log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def _add_private_message(self, name, message, event_type="private"):
        entry = {
            "time": utils.get_timer().get_date("%Y%m%d-%H:%M"),
            "game_index": self.config.get("game_index", 1),
            "round": self.config.get("round", 1),
            "phase": self.config.get("phase", ""),
            "event_type": event_type,
            "message": message,
        }
        self.config["private_messages"].setdefault(name, []).append(entry)
        return entry

    def latest_public_message(self):
        if not self.config["messages"]:
            return ""
        return self.config["messages"][-1]["message"]

    def latest_private_message(self, name):
        messages = self.config["private_messages"].get(name, [])
        if not messages:
            return ""
        return messages[-1]["message"]

    def _phase_window(self, phase):
        if phase == "sequential_vote":
            start, _ = self._base_phase_window("sequential_vote")
            return start, self._sequential_vote_end_minute()
        if phase == "afternoon_discussion":
            _, end = self._base_phase_window("afternoon_discussion")
            return self._sequential_vote_end_minute(), end
        return self._base_phase_window(phase)

    def _phase_action_key_for(self, phase):
        window = ""
        if phase == "night_action":
            window = "night"
        return "{}:{}:{}:{}".format(
            self.config.get("current_date"),
            self.config.get("round", 1),
            phase,
            window,
        )

    def _morning_meeting_phase_key(self):
        return self._phase_action_key_for("morning_meeting")

    def _sequential_vote_phase_key(self):
        return self._phase_action_key_for("sequential_vote")

    def _sequential_vote_order(self):
        order = self._speech_order(self._morning_meeting_phase_key())
        alive = self.alive_players()
        order = [name for name in order if name in alive]
        order.extend(name for name in alive if name not in order)
        return order

    def _sequential_vote_slot_minutes(self, order=None):
        order = order or self._sequential_vote_order()
        start, end = self._base_phase_window("sequential_vote")
        available = end - start
        actor_count = max(1, len(order))
        configured = self._configured_minutes(
            "sequential_vote_slot_minutes", SEQUENTIAL_VOTE_SLOT_MINUTES, 1
        )
        return max(1, min(configured, max(1, available // actor_count)))

    def _sequential_vote_end_minute(self):
        order = self._sequential_vote_order()
        slot_minutes = self._sequential_vote_slot_minutes(order)
        start, end = self._base_phase_window("sequential_vote")
        return min(end, start + max(1, len(order)) * slot_minutes)

    def _sequential_vote_turn(self):
        if self.config.get("phase") != "sequential_vote":
            return {}
        order = self._sequential_vote_order()
        if not order:
            return {}
        start, end = self._phase_window("sequential_vote")
        minute = self._logical_minute()
        if minute < start or minute >= end:
            return {}
        slot_minutes = self._sequential_vote_slot_minutes(order)
        index = min(len(order) - 1, max(0, minute - start) // slot_minutes)
        voter = order[index]
        actions = self.config["actions"].get(self._sequential_vote_phase_key(), {})
        if voter in actions:
            return {}
        return {
            "voter": voter,
            "index": index + 1,
            "count": len(order),
            "slot_minutes": slot_minutes,
        }

    def _speech_preference_minutes(self):
        return self._configured_minutes(
            "speech_preference_minutes", SPEECH_PREFERENCE_MINUTES, 0
        )

    def _speech_order_vote_minutes(self):
        return max(
            self._speech_preference_minutes(),
            self._configured_minutes(
                "speech_order_vote_minutes", SPEECH_ORDER_VOTE_MINUTES, 0
            ),
        )

    def _morning_meeting_elapsed(self):
        start, _ = self._phase_window("morning_meeting")
        return max(0, self._logical_minute() - start)

    def _speech_stage(self):
        if self.config.get("phase") != "morning_meeting":
            return ""
        elapsed = self._morning_meeting_elapsed()
        if elapsed < self._speech_preference_minutes():
            return "preference"
        if elapsed < self._speech_order_vote_minutes():
            return "vote"
        return "speech"

    def _speech_order(self, phase_key=None):
        phase_key = phase_key or self.phase_action_key()
        alive = self.alive_players()
        configured = self.config["speech_orders"].get(phase_key, [])
        ordered = [name for name in configured if name in alive]
        ordered.extend(name for name in alive if name not in ordered)
        return ordered

    def _speech_preferences_summary(self, phase_key=None):
        phase_key = phase_key or self.phase_action_key()
        preferences = self.config["speech_preferences"].get(phase_key, {})
        parts = []
        for name in self.alive_players():
            preference = preferences.get(name, {}).get("preference", "无所谓")
            parts.append("{}希望{}".format(name, preference))
        return "、".join(parts) if parts else "暂无申报"

    def _normalize_speech_preference(self, target):
        if target in SPEECH_PREFERENCE_OPTIONS:
            return target
        target = str(target or "")
        for option in SPEECH_PREFERENCE_OPTIONS:
            if option in target:
                return option
        return None

    def _candidate_from_text(self, text, candidates):
        text = str(text or "").strip()
        if text in candidates:
            return text
        for candidate in candidates:
            if candidate in text:
                return candidate
        return None

    def _normalize_speech_order_vote(self, target, candidates):
        if isinstance(target, str):
            items = [target]
        elif isinstance(target, (list, tuple)):
            items = list(target)
        else:
            items = []

        ordered = []
        if len(items) == 1 and isinstance(items[0], str):
            text = items[0]
            indexed = []
            for candidate in candidates:
                pos = text.find(candidate)
                if pos >= 0:
                    indexed.append((pos, candidate))
            if indexed:
                items = [candidate for _, candidate in sorted(indexed)]

        for item in items:
            candidate = self._candidate_from_text(item, candidates)
            if candidate and candidate not in ordered:
                ordered.append(candidate)
        ordered.extend(candidate for candidate in candidates if candidate not in ordered)
        return ordered

    def _record_speech_preference(self, name, context, target):
        phase_key = context.get("phase_action_key") or self.phase_action_key()
        preference = self._normalize_speech_preference(target)
        if not preference:
            return False
        preferences = self.config["speech_preferences"].setdefault(phase_key, {})
        if name in preferences:
            return False
        preferences[name] = {
            "time": utils.get_timer().get_date("%Y%m%d-%H:%M"),
            "round": self.config.get("round", 1),
            "phase": self.config.get("phase", ""),
            "role": context.get("role", "未分配"),
            "preference": preference,
        }
        actions = self.config["actions"].setdefault(
            "{}:speech_preference".format(phase_key), {}
        )
        actions[name] = {
            "time": preferences[name]["time"],
            "round": preferences[name]["round"],
            "phase": preferences[name]["phase"],
            "role": preferences[name]["role"],
            "required_action": context.get("required_action"),
            "target": preference,
        }
        self.recorder.record_speech_preference(
            self.config,
            phase_key,
            name,
            preferences[name],
            context.get("candidate_targets", []),
        )
        return True

    def _record_speech_order_vote(self, name, context, target):
        phase_key = context.get("phase_action_key") or self.phase_action_key()
        candidates = [p for p in context.get("candidate_targets", []) if p != self.game_master_name]
        if not candidates:
            return False
        order = self._normalize_speech_order_vote(target, candidates)
        if sorted(order) != sorted(candidates):
            return False
        votes = self.config["speech_order_votes"].setdefault(phase_key, {})
        if name in votes:
            return False
        votes[name] = {
            "time": utils.get_timer().get_date("%Y%m%d-%H:%M"),
            "round": self.config.get("round", 1),
            "phase": self.config.get("phase", ""),
            "role": context.get("role", "未分配"),
            "order": order,
        }
        actions = self.config["actions"].setdefault(
            "{}:speech_order_vote".format(phase_key), {}
        )
        actions[name] = {
            "time": votes[name]["time"],
            "round": votes[name]["round"],
            "phase": votes[name]["phase"],
            "role": votes[name]["role"],
            "required_action": context.get("required_action"),
            "target": order,
        }
        self.recorder.record_speech_order_vote(
            self.config,
            phase_key,
            name,
            votes[name],
            candidates,
        )
        return True

    def _resolve_speech_preferences_if_ready(self, phase_key, allow_partial=False):
        alive = self.alive_players()
        if not alive:
            return
        preferences = self.config["speech_preferences"].setdefault(phase_key, {})
        if not allow_partial and any(name not in preferences for name in alive):
            return
        for name in alive:
            preferences.setdefault(
                name,
                {
                    "time": utils.get_timer().get_date("%Y%m%d-%H:%M"),
                    "round": self.config.get("round", 1),
                    "phase": self.config.get("phase", ""),
                    "role": self.config["players"][name].get("role", "未分配"),
                    "preference": "无所谓",
                },
            )
        if self.config["speech_preference_announced"].get(phase_key):
            return
        self.config["speech_preference_announced"][phase_key] = True
        self.recorder.record_speech_preferences_resolved(
            self.config, phase_key, preferences
        )
        self.publish(
            "speech_preferences_collected",
            "发言意愿申报结束：{}。现在请所有存活玩家据此投票决定今天上午的正式发言顺序。".format(
                self._speech_preferences_summary(phase_key)
            ),
            self.public_info(),
            force=True,
        )

    def _preference_tiebreak(self, name, phase_key):
        preference = (
            self.config["speech_preferences"]
            .get(phase_key, {})
            .get(name, {})
            .get("preference", "无所谓")
        )
        ranks = {
            "尽早发言": 0,
            "中段发言": 1,
            "无所谓": 1,
            "靠后发言": 2,
            "最后发言": 3,
        }
        return ranks.get(preference, 1)

    def _resolve_speech_order_if_ready(self, phase_key, allow_partial=False):
        alive = self.alive_players()
        if not alive:
            return
        votes = self.config["speech_order_votes"].setdefault(phase_key, {})
        if not allow_partial and any(name not in votes for name in alive):
            return
        for name in alive:
            votes.setdefault(
                name,
                {
                    "time": utils.get_timer().get_date("%Y%m%d-%H:%M"),
                    "round": self.config.get("round", 1),
                    "phase": self.config.get("phase", ""),
                    "role": self.config["players"][name].get("role", "未分配"),
                    "order": list(alive),
                },
            )

        scores = {name: 0 for name in alive}
        for vote in votes.values():
            order = self._normalize_speech_order_vote(vote.get("order", []), alive)
            for index, candidate in enumerate(order):
                scores[candidate] += len(alive) - index

        original_index = {name: index for index, name in enumerate(alive)}
        order = sorted(
            alive,
            key=lambda name: (
                -scores.get(name, 0),
                self._preference_tiebreak(name, phase_key),
                original_index[name],
            ),
        )
        self.config["speech_orders"][phase_key] = order
        self.config["speech_order_scores"][phase_key] = scores
        if self.config["speech_order_announced"].get(phase_key):
            return
        self.config["speech_order_announced"][phase_key] = True
        self.recorder.record_speech_order_resolved(
            self.config,
            phase_key,
            order,
            scores,
            votes,
            self.config["speech_preferences"].get(phase_key, {}),
        )
        order_text = "、".join(
            "{}.{}".format(index + 1, name) for index, name in enumerate(order)
        )
        score_text = "，".join(
            "{}{}分".format(name, scores[name]) for name in order
        )
        self.publish(
            "speech_order_resolved",
            "发言顺序投票结束。今天上午正式发言顺序为：{}。计分：{}。".format(
                order_text, score_text
            ),
            self.public_info(),
            force=True,
        )

    def _resolve_speech_meeting_if_ready(self, phase_key):
        stage = self._speech_stage()
        if stage == "preference":
            self._resolve_speech_preferences_if_ready(phase_key)
        elif stage == "vote":
            self._resolve_speech_preferences_if_ready(phase_key, allow_partial=True)
            self._resolve_speech_order_if_ready(phase_key)
        elif stage == "speech":
            self._resolve_speech_preferences_if_ready(phase_key, allow_partial=True)
            self._resolve_speech_order_if_ready(phase_key, allow_partial=True)

    def _morning_meeting_turn(self):
        if self.config.get("phase") != "morning_meeting":
            return {}
        if self._speech_stage() != "speech":
            return {}
        phase_key = self.phase_action_key()
        order = self._speech_order(phase_key)
        if not order:
            return {}
        start, end = self._phase_window("morning_meeting")
        speech_start = min(end, start + self._speech_order_vote_minutes())
        minute = self._logical_minute()
        if minute < speech_start or minute >= end:
            return {}
        slot_minutes = self._speech_slot_minutes()
        speeches = self.config.setdefault("speech_texts", {}).get(phase_key, {})
        current_time = utils.get_timer().get_date("%Y%m%d-%H:%M")
        turns = self.config.setdefault("speech_turns", {})
        turn = turns.get(phase_key, {})
        speaker = turn.get("speaker") if turn.get("time") == current_time else None
        if speaker not in order:
            speaker = next((name for name in order if name not in speeches), None)
            turns[phase_key] = {"time": current_time, "speaker": speaker}
        if not speaker:
            return {}
        index = order.index(speaker)
        return {
            "speaker": speaker,
            "index": index + 1,
            "count": len(order),
            "slot_minutes": slot_minutes,
        }

    def _speech_context_phase_key(self):
        if self.config.get("phase") == "morning_meeting":
            return self.phase_action_key()
        return self._morning_meeting_phase_key()

    def _format_speech_history(self, phase_key=None):
        phase_key = phase_key or self._speech_context_phase_key()
        all_speeches = self.config.setdefault("speech_texts", {})
        speeches = all_speeches.get(phase_key, {})
        if not speeches and all_speeches:
            phase_key = sorted(all_speeches.keys())[-1]
            speeches = all_speeches.get(phase_key, {})
        if not speeches:
            return "暂无正式发言"
        order = self._speech_order(phase_key)
        ordered_names = [name for name in order if name in speeches]
        ordered_names.extend(name for name in speeches if name not in ordered_names)
        return "\n".join(
            "{}：{}".format(name, speeches[name]) for name in ordered_names
        )

    def has_morning_speech(self, name, context=None):
        context = context or {}
        phase_key = context.get("phase_action_key") or self.phase_action_key()
        return name in self.config.setdefault("speech_texts", {}).get(phase_key, {})

    def record_morning_speech(self, name, context, text):
        phase_key = context.get("phase_action_key") or self.phase_action_key()
        if context.get("required_action") != "give_morning_speech":
            return False
        if self.has_morning_speech(name, context):
            return False
        text = str(text or "").strip()
        if not text:
            return False
        speeches = self.config.setdefault("speech_texts", {}).setdefault(phase_key, {})
        speeches[name] = text
        self.recorder.record_morning_speech(self.config, phase_key, name, text)
        return True

    def alive_wolves(self):
        return [
            name
            for name, player in self.config["players"].items()
            if player.get("alive") and player.get("role") == "狼人"
        ]

    def _format_wolf_discussion_history(self, phase_key=None):
        phase_key = phase_key or self.phase_action_key()
        discussions = self.config.setdefault("wolf_discussions", {}).get(phase_key, {})
        if not discussions:
            return "暂无狼人讨论"
        ordered_names = [name for name in self.alive_wolves() if name in discussions]
        ordered_names.extend(name for name in discussions if name not in ordered_names)
        return "\n".join(
            "{}：{}".format(name, discussions[name].get("message", ""))
            for name in ordered_names
        )

    def has_wolf_discussion(self, name, context=None):
        context = context or {}
        phase_key = context.get("phase_action_key") or self.phase_action_key()
        return name in self.config.setdefault("wolf_discussions", {}).get(phase_key, {})

    def wolf_discussions_ready(self, phase_key=None):
        phase_key = phase_key or self.phase_action_key()
        wolves = self.alive_wolves()
        if not wolves:
            return False
        discussions = self.config.setdefault("wolf_discussions", {}).get(phase_key, {})
        return all(wolf in discussions for wolf in wolves)

    def record_wolf_discussion(self, name, context, discussion):
        phase_key = context.get("phase_action_key") or self.phase_action_key()
        if context.get("required_action") != "discuss_werewolf_kill":
            return False
        if self.has_wolf_discussion(name, context):
            return False
        candidates = context.get("candidate_targets", [])
        if isinstance(candidates, str):
            candidates = [i.strip() for i in candidates.split("、") if i.strip()]
        if isinstance(discussion, str):
            data = {"target": discussion, "message": discussion}
        else:
            data = dict(discussion or {})
        target = self._candidate_from_text(data.get("target"), candidates)
        if not target:
            return False
        message = str(data.get("message") or "").strip()
        if not message:
            message = "我建议今晚击杀{}。".format(target)
        record = {
            "time": utils.get_timer().get_date("%Y%m%d-%H:%M"),
            "round": self.config.get("round", 1),
            "phase": self.config.get("phase", ""),
            "role": context.get("role", "未分配"),
            "target": target,
            "message": message,
        }
        discussions = self.config.setdefault("wolf_discussions", {}).setdefault(
            phase_key, {}
        )
        discussions[name] = record
        self.recorder.record_wolf_discussion(
            self.config, phase_key, name, record, candidates
        )
        return True

    def context_for(self, name):
        self.update_phase()
        if name not in self.config["players"]:
            return {}
        player = self.config["players"][name]
        if self.config["phase"] == "morning_mirror" and player.get("alive"):
            self.config["checked_dates"][name] = self.config["current_date"]
        phase_key = self.phase_action_key()
        instruction = self._private_phase_instruction(name, player)
        meeting_turn = self._morning_meeting_turn()
        vote_turn = self._sequential_vote_turn()
        night_stage, night_stage_name = self._night_stage()
        speech_order_key = (
            self._morning_meeting_phase_key()
            if self.config.get("phase") in {"sequential_vote", "afternoon_discussion"}
            else phase_key
        )
        public_info = self.public_info()
        return {
            "enabled": True,
            "agent": name,
            "game_index": self.config.get("game_index", 1),
            "public_rules": self.public_rules(),
            "round": self.config.get("round", 1),
            "phase": self.config.get("phase", ""),
            "phase_name": self.config.get("phase_name", ""),
            "night_stage": night_stage,
            "night_stage_name": night_stage_name,
            "phase_action_key": phase_key,
            "role": player.get("role", "未分配"),
            "team": player.get("team", "未知"),
            "alive": player.get("alive", True),
            "magic_mirror_message": self._magic_mirror_message_for_prompt(),
            "mirror_mode": self.config.get("mirror_mode", "none"),
            "current_mirror_announcement": self.config.get(
                "current_mirror_announcement"
            ),
            "current_mirror_line_index": self.config.get(
                "current_mirror_line_index"
            ),
            "private_message": self.latest_private_message(name),
            "phase_instruction": instruction["message"],
            "required_action": instruction["required_action"],
            "candidate_targets": instruction["candidate_targets"],
            "alive_players": public_info.get("alive_players", []),
            "dead_last_night": public_info.get("dead_last_night", []),
            "exiled_player": public_info.get("exiled_player"),
            "meeting_speaker": meeting_turn.get("speaker"),
            "meeting_speaker_index": meeting_turn.get("index"),
            "meeting_speaker_count": meeting_turn.get("count"),
            "vote_turn": vote_turn.get("voter"),
            "vote_turn_index": vote_turn.get("index"),
            "vote_turn_count": vote_turn.get("count"),
            "speech_meeting_stage": self._speech_stage(),
            "speech_preferences": self.config["speech_preferences"].get(phase_key, {}),
            "speech_order": self._speech_order(speech_order_key),
            "speech_history": self._format_speech_history(speech_order_key),
            "wolf_discussion_history": self._format_wolf_discussion_history(phase_key),
            "checked_magic_mirror_today": self.config["checked_dates"].get(name)
            == self.config["current_date"],
        }

    def use(self, name):
        """Return the public and private mirror information for one player."""
        return self.context_for(name)

    def should_collect_choice(self, context):
        if not context:
            return False
        if self.config.get("winner"):
            return False
        if not context.get("candidate_targets"):
            return False
        required_action = context.get("required_action")
        if required_action == "choose_hunter_shot_target":
            return True
        if not context.get("alive", True):
            return False
        if required_action == "choose_speech_preference":
            actor = context.get("agent")
            phase_key = context.get("phase_action_key") or self.phase_action_key()
            return actor not in self.config["speech_preferences"].get(phase_key, {})
        if required_action == "choose_speech_order_vote":
            actor = context.get("agent")
            phase_key = context.get("phase_action_key") or self.phase_action_key()
            return actor not in self.config["speech_order_votes"].get(phase_key, {})
        if required_action == "choose_vote_target" and self._should_skip_vote():
            return False
        if required_action == "choose_vote_target":
            actor = context.get("agent")
            phase_key = context.get("phase_action_key") or self.phase_action_key()
            return actor not in self.config["actions"].get(phase_key, {})
        if required_action in {
            "choose_vote_target",
            "choose_werewolf_kill_target",
            "choose_seer_check_target",
            "choose_guard_target",
            "choose_witch_action",
        }:
            actor = context.get("agent")
            phase_key = context.get("phase_action_key") or self.phase_action_key()
            return actor not in self.config["actions"].get(phase_key, {})
        return False

    def record_choice(self, name, context, target):
        if not self.should_collect_choice(context):
            return False
        required_action = context.get("required_action")
        if required_action == "choose_speech_preference":
            return self._record_speech_preference(name, context, target)
        if required_action == "choose_speech_order_vote":
            return self._record_speech_order_vote(name, context, target)
        candidates = context.get("candidate_targets", [])
        if target not in candidates or target == self.game_master_name:
            return False
        if (
            required_action == "choose_guard_target"
            and target == self._last_guard_target()
        ):
            return False
        phase_key = (
            "hunter_shots"
            if required_action == "choose_hunter_shot_target"
            else context.get("phase_action_key") or self.phase_action_key()
        )
        actions = self.config["actions"].setdefault(phase_key, {})
        if name in actions:
            return False
        actions[name] = {
            "time": utils.get_timer().get_date("%Y%m%d-%H:%M"),
            "round": self.config.get("round", 1),
            "phase": self.config.get("phase", ""),
            "role": context.get("role", "未分配"),
            "required_action": required_action,
            "target": target,
        }
        if required_action == "choose_vote_target":
            vote_order = (
                self._sequential_vote_order()
                if phase_key == self._sequential_vote_phase_key()
                else self.alive_players()
            )
            self.recorder.record_vote_choice(
                self.config, phase_key, name, actions[name], candidates, vote_order
            )
        elif required_action in {
            "choose_werewolf_kill_target",
            "choose_seer_check_target",
            "choose_guard_target",
            "choose_witch_action",
            "choose_hunter_shot_target",
        }:
            self.recorder.record_special_action(
                self.config, phase_key, name, actions[name], candidates
            )
        return True

    def resolve_if_ready(self):
        self.update_phase()
        if self.config.get("winner"):
            return
        self._resolve_hunter_shots()
        if self.config.get("winner"):
            return
        phase = self.config.get("phase")
        phase_key = self.phase_action_key()
        if phase_key in self.config["resolved_phase_keys"]:
            return
        if phase == "sequential_vote":
            self._resolve_vote_if_ready(phase_key)
        elif phase in {"afternoon_discussion", "exile_result"}:
            vote_phase_key = self._sequential_vote_phase_key()
            if vote_phase_key not in self.config["resolved_phase_keys"]:
                self._resolve_vote_if_ready(vote_phase_key, allow_partial=True)
        elif phase == "dusk_vote":
            self._resolve_vote_if_ready(phase_key)
        elif phase == "night_action":
            self._resolve_night_if_ready(phase_key)
        elif phase == "morning_meeting":
            self._resolve_speech_meeting_if_ready(phase_key)

    def phase_action_key(self):
        return self._phase_action_key_for(self.config.get("phase", ""))

    def _resolve_vote_if_ready(self, phase_key, allow_partial=False):
        if self._should_skip_vote():
            self._mark_resolved(phase_key)
            return
        voters = self.alive_players()
        actions = self.config["actions"].get(phase_key, {})
        if not allow_partial and any(voter not in actions for voter in voters):
            return
        vote_order = (
            self._sequential_vote_order()
            if phase_key == self._sequential_vote_phase_key()
            else list(voters)
        )
        tally = {}
        for vote in actions.values():
            target = vote["target"]
            tally[target] = tally.get(target, 0) + 1
        if not tally:
            self.recorder.record_vote_resolved(
                self.config, phase_key, actions, tally, None, vote_order
            )
            self.publish(
                "vote_exile",
                "第{}轮投票结束。没有收到有效票，暂时无人被放逐。".format(
                    self.config.get("round", 1)
                ),
                self.public_info(),
                force=True,
            )
            self._mark_resolved(phase_key)
            return
        exiled = sorted(tally.items(), key=lambda item: (-item[1], item[0]))[0][0]
        self._kill_player(exiled, "vote_exile")
        self.config["exiled_player"] = exiled
        self.config["exiled_round"] = self.config.get("round", 1)
        self.recorder.record_vote_resolved(
            self.config, phase_key, actions, tally, exiled, vote_order
        )
        vote_text = "，".join("{}{}票".format(name, count) for name, count in sorted(tally.items()))
        self.publish(
            "vote_exile",
            "第{}轮投票结束。投票结果：{}。被放逐玩家为：{}。".format(
                self.config.get("round", 1), vote_text, exiled
            ),
            self.public_info(),
            force=True,
        )
        self._mark_resolved(phase_key)
        self._check_winner()

    def _resolve_night_if_ready(self, phase_key):
        actions = self.config["actions"].get(phase_key, {})
        expected = self._night_expected_actors()
        if any(actor not in actions for actor in expected):
            return

        wolf_target = self._current_wolf_attack_target(phase_key)
        guard_target = self._current_guard_target(phase_key)
        witch = self._alive_witch()
        if witch and self._witch_candidates(witch, phase_key) and witch not in actions:
            self._ensure_witch_attack_notice(witch, wolf_target)
            return

        witch_action = actions.get(witch, {}).get("target") if witch else None
        saved_target, poison_target = self._parse_witch_action(witch, witch_action)

        guard_target = None
        seer_results = []
        for actor, action in actions.items():
            role = self.config["players"][actor]["role"]
            if role == "守卫":
                guard_target = action["target"]
            elif role == "预言家":
                result = self._resolve_seer_check(actor, action["target"], phase_key)
                if result:
                    seer_results.append(result)

        deaths = []
        if wolf_target:
            if wolf_target != guard_target and wolf_target != saved_target:
                self._kill_player(wolf_target, "werewolf_kill")
                deaths.append(wolf_target)
        if poison_target and poison_target not in deaths:
            if self._kill_player(poison_target, "witch_poison"):
                deaths.append(poison_target)

        self.config["dead_last_night"] = deaths
        self.config["dead_last_night_round"] = self.config.get("round", 1)
        if guard_target:
            self.config["last_guard_target"] = guard_target
        self.recorder.record_special_result(
            self.config,
            phase_key,
            "night_resolved",
            {
                "wolf_target": wolf_target,
                "guard_target": guard_target,
                "witch_action": witch_action,
                "saved_target": saved_target,
                "poison_target": poison_target,
                "seer_results": seer_results,
                "deaths": list(deaths),
            },
        )
        self.publish(
            "night_resolved",
            "第{}轮夜晚行动已结算。天亮后魔镜将公布昨晚死亡玩家。".format(
                self.config.get("round", 1)
            ),
            self.public_info(),
            force=True,
        )
        self._mark_resolved(phase_key)
        self._check_winner()

    def _night_expected_actors(self):
        actors = []
        for name, player in self.config["players"].items():
            if not player.get("alive"):
                continue
            if player.get("role") in {"狼人", "预言家", "守卫"}:
                actors.append(name)
        return actors

    def _current_wolf_attack_target(self, phase_key=None):
        phase_key = phase_key or self.phase_action_key()
        actions = self.config["actions"].get(phase_key, {})
        wolves = [
            name
            for name, player in self.config["players"].items()
            if player.get("alive") and player.get("role") == "狼人"
        ]
        if any(wolf not in actions for wolf in wolves):
            return None
        wolf_targets = [actions[wolf]["target"] for wolf in wolves if wolf in actions]
        if not wolf_targets:
            return None
        return sorted(
            ((target, wolf_targets.count(target)) for target in set(wolf_targets)),
            key=lambda item: (-item[1], item[0]),
        )[0][0]

    def _current_guard_target(self, phase_key=None):
        phase_key = phase_key or self.phase_action_key()
        actions = self.config["actions"].get(phase_key, {})
        for actor, action in actions.items():
            player = self.config["players"].get(actor, {})
            if player.get("alive") and player.get("role") == "守卫":
                return action["target"]
        return None

    def _last_guard_target(self):
        target = self.config.get("last_guard_target")
        if target:
            return target

        current_phase_key = self.phase_action_key()
        guard_actions = []
        resolved_phase_keys = set(self.config.get("resolved_phase_keys", []))
        for phase_key, actions in self.config.get("actions", {}).items():
            if phase_key == current_phase_key or ":night_action:" not in phase_key:
                continue
            if phase_key not in resolved_phase_keys:
                continue
            for action in actions.values():
                if action.get("role") == "守卫" and action.get("target"):
                    guard_actions.append(
                        (action.get("time", ""), phase_key, action["target"])
                    )
        if not guard_actions:
            return None
        return sorted(guard_actions)[-1][2]

    def _alive_witch(self):
        for name, player in self.config["players"].items():
            if player.get("alive") and player.get("role") == "女巫":
                return name
        return None

    def _witch_candidates(self, witch, phase_key=None):
        player = self.config["players"].get(witch, {})
        if not player.get("alive") or player.get("role") != "女巫":
            return []
        candidates = []
        wolf_target = self._current_wolf_attack_target(phase_key)
        guard_target = self._current_guard_target(phase_key)
        if wolf_target and wolf_target != guard_target and player.get("witch_antidote"):
            candidates.append("使用解药救{}".format(wolf_target))
        if player.get("witch_poison"):
            candidates.extend(
                "使用毒药毒{}".format(name)
                for name in self.alive_players()
                if name != witch
            )
        if candidates:
            candidates.append("放弃")
        return candidates

    def _ensure_witch_attack_notice(self, witch, wolf_target):
        notice_key = "{}:{}".format(self.phase_action_key(), witch)
        if self.config.setdefault("witch_notices", {}).get(notice_key):
            return
        if wolf_target:
            message = "今晚狼人袭击的目标是：{}。你可以根据候选列表选择是否使用解药、毒药或放弃。".format(wolf_target)
        else:
            message = "今晚还没有确定狼人袭击目标。请等待魔镜后续提示。"
        self._add_private_message(witch, message, event_type="witch_night_notice")
        self.config["witch_notices"][notice_key] = True

    def _parse_witch_action(self, witch, action):
        saved_target, poison_target = None, None
        if not witch or not action or action == "放弃":
            return saved_target, poison_target
        player = self.config["players"].get(witch, {})
        if action.startswith("使用解药救") and player.get("witch_antidote"):
            saved_target = action[len("使用解药救"):]
            player["witch_antidote"] = False
            self._add_private_message(
                witch,
                "你使用了解药，救下了{}。".format(saved_target),
                event_type="witch_antidote_used",
            )
        elif action.startswith("使用毒药毒") and player.get("witch_poison"):
            poison_target = action[len("使用毒药毒"):]
            player["witch_poison"] = False
            self._add_private_message(
                witch,
                "你使用了毒药，目标是{}。".format(poison_target),
                event_type="witch_poison_used",
            )
        return saved_target, poison_target

    def _resolve_seer_check(self, seer, target, phase_key=None):
        player = self.config["players"].get(target)
        if not player:
            return None
        result = "狼人阵营" if player.get("role") == "狼人" else "好人阵营"
        self._add_private_message(
            seer,
            "你查验了{}。魔镜告诉你：{}属于{}。".format(target, target, result),
            event_type="seer_check_result",
        )
        data = {
            "seer": seer,
            "target": target,
            "result": result,
            "target_role": player.get("role"),
        }
        self.recorder.record_special_result(
            self.config,
            phase_key or self.phase_action_key(),
            "seer_check_result",
            data,
        )
        return data

    def _kill_player(self, name, reason):
        player = self.config["players"].get(name)
        if not player or not player.get("alive"):
            return False
        player["alive"] = False
        self.config["dead_history"].append(
            {
                "round": self.config.get("round", 1),
                "phase": self.config.get("phase", ""),
                "name": name,
                "reason": reason,
            }
        )
        self.recorder.record_death(self.config, name, reason, player)
        self._add_private_message(
            name,
            "你已经死亡并进入放逐状态。请前往放逐区等待；除非魔镜明确允许遗言或猎人开枪，否则你不能发言、投票或使用技能。",
            event_type="death_notice",
        )
        if (
            player.get("role") == "猎人"
            and player.get("hunter_shot_available")
            and not player.get("hunter_shot_used")
        ):
            self.config["hunter_pending_shots"][name] = True
            self._add_private_message(
                name,
                "你是猎人，死亡后可以在放逐区开枪。请从魔镜给出的合法候选列表中选择一名目标，或选择放弃。",
                event_type="hunter_shot_notice",
            )
        return True

    def _resolve_hunter_shots(self):
        actions = self.config["actions"].get("hunter_shots", {})
        for hunter, pending in list(self.config["hunter_pending_shots"].items()):
            if not pending or hunter not in actions:
                continue
            player = self.config["players"].get(hunter, {})
            target = actions[hunter]["target"]
            player["hunter_shot_available"] = False
            player["hunter_shot_used"] = True
            self.config["hunter_pending_shots"][hunter] = False
            if target == "放弃":
                self.recorder.record_special_result(
                    self.config,
                    "hunter_shots",
                    "hunter_shot_skipped",
                    {"hunter": hunter, "target": target},
                )
                self.publish(
                    "hunter_shot_skipped",
                    "{}选择不发动猎人技能。".format(hunter),
                    self.public_info(),
                    force=True,
                )
                self._check_winner()
                continue
            if target in self.alive_players() and self._kill_player(target, "hunter_shot"):
                self.recorder.record_special_result(
                    self.config,
                    "hunter_shots",
                    "hunter_shot",
                    {"hunter": hunter, "target": target},
                )
                self.publish(
                    "hunter_shot",
                    "{}发动猎人技能，带走了{}。".format(hunter, target),
                    self.public_info(),
                    force=True,
                )
                self._check_winner()

    def _check_winner(self):
        if self.config.get("winner"):
            return
        if any(self.config.get("hunter_pending_shots", {}).values()):
            return
        alive = [
            p
            for p in self.config["players"].values()
            if p.get("alive") and not p.get("is_game_master")
        ]
        wolves = [p for p in alive if p.get("role") == "狼人"]
        good = [p for p in alive if p.get("role") != "狼人"]
        winner, reason = None, ""
        if not wolves:
            winner = "好人阵营"
            reason = "所有狼人均已出局。"
        elif self.config.get("wolf_win_condition") == "parity":
            if len(wolves) >= len(good):
                winner = "狼人阵营"
                reason = "存活狼人数量已经不少于存活好人数量。"
        else:
            villager_role = self.config.get("villager_role", DEFAULT_VILLAGER_ROLE)
            god_roles = set(self.config.get("god_roles") or DEFAULT_GOD_ROLES)
            villagers = [p for p in good if p.get("role") == villager_role]
            gods = [p for p in good if p.get("role") in god_roles]
            if not villagers:
                winner = "狼人阵营"
                reason = "所有平民均已出局，狼人完成屠民。"
            elif not gods:
                winner = "狼人阵营"
                reason = "所有神职均已出局，狼人完成屠神。"
        if not winner:
            return
        self.config["winner"] = winner
        self.config["winner_reason"] = reason
        self.publish(
            "game_over",
            "游戏结束。获胜阵营为：{}。原因：{}".format(winner, reason),
            self.public_info(),
            force=True,
        )
        self.recorder.close_game(self.config)
        self._record_fyp_finished_game()

    def _record_fyp_finished_game(self):
        try:
            self.fyp_stats.record_finished_game(self.config)
        except Exception as exc:
            if hasattr(self.logger, "info"):
                self.logger.info("FYP stats write failed: {}".format(exc))

    def _mark_resolved(self, phase_key):
        if phase_key not in self.config["resolved_phase_keys"]:
            self.config["resolved_phase_keys"].append(phase_key)

    def _private_phase_instruction(self, name, player):
        if self.config["hunter_pending_shots"].get(name):
            candidates = [p for p in self.alive_players() if p != name]
            candidates.append("放弃")
            return self._instruction(
                "choose_hunter_shot_target",
                candidates,
                "你已经死亡并进入放逐状态，但你是猎人，魔镜允许你发动一次猎人技能；请在放逐区从合法候选列表中选择一名目标开枪，或选择放弃。",
            )
        if not player.get("alive", True):
            return self._instruction(
                "dead_wait",
                [],
                "你已经死亡并进入放逐状态。请前往放逐区等待；除非魔镜明确允许遗言或猎人开枪，否则你不能发言、投票或使用技能。",
            )

        phase = self.config.get("phase")
        if phase == "morning_mirror":
            return self._instruction(
                "check_magic_mirror",
                [],
                "你今天早上必须先查看魔镜，读取公开公告和自己的私密提示，然后再开始其他行动。",
            )
        if phase == "sequential_vote":
            if self._should_skip_vote():
                return self._instruction(
                    "stay_in_room_locked",
                    [],
                    "第一天不进行投票放逐。会议结束后你必须待在自己的房间内整理线索，禁止串门和自由讨论。",
                )
            if self.config.get("sequential_vote_batch", True):
                phase_key = self.phase_action_key()
                actions = self.config["actions"].get(phase_key, {})
                if name not in actions:
                    candidates = [p for p in self.alive_players() if p != name]
                    order = self._sequential_vote_order()
                    index = order.index(name) + 1 if name in order else len(order)
                    return self._instruction(
                        "choose_vote_target",
                        candidates,
                        "现在进入集中顺序投票收集。你的发言顺序为第{} / {}位；前往投票区，只能从候选列表中选择一名玩家，不能选择魔镜。".format(
                            index,
                            len(order),
                        ),
                    )
                return self._instruction(
                    "wait_vote_turn_locked",
                    [],
                    "你已经提交了本轮投票。请回到自己的房间等待魔镜公布放逐结果，禁止串门和自由讨论。",
                )
            vote_turn = self._sequential_vote_turn()
            voter = vote_turn.get("voter")
            if name == voter:
                candidates = [p for p in self.alive_players() if p != name]
                return self._instruction(
                    "choose_vote_target",
                    candidates,
                    "现在轮到你按上午发言顺序投票（第{} / {}位）。前往投票区，只能从候选列表中选择一名玩家，不能选择魔镜。".format(
                        vote_turn.get("index", 1),
                        vote_turn.get("count", 1),
                    ),
                )
            if voter:
                return self._instruction(
                    "wait_vote_turn_locked",
                    [],
                    "当前轮到{}前往投票区投票。你必须留在自己的房间等待自己的投票轮次，禁止串门和自由讨论。".format(
                        voter
                    ),
                )
            return self._instruction(
                "wait_vote_turn_locked",
                [],
                "当前投票轮次已完成或正在切换。你必须留在自己的房间等待魔镜下一步指令，禁止串门和自由讨论。",
            )
        if phase == "dusk_vote":
            if self._should_skip_vote():
                return self._instruction(
                    "join_free_discussion",
                    [],
                    "第一天不进行投票放逐。继续参与讨论、观察发言和整理线索，不要提交投票目标。",
                )
            candidates = [p for p in self.alive_players() if p != name]
            return self._instruction(
                "choose_vote_target",
                candidates,
                "现在需要投票。你只能从候选列表中选择一名玩家，不能选择魔镜。",
            )
        if phase == "night_action":
            return self._night_instruction(name, player)
        if phase == "morning_meeting":
            phase_key = self.phase_action_key()
            stage = self._speech_stage()
            if stage == "preference":
                preferences = self.config["speech_preferences"].get(phase_key, {})
                if name in preferences:
                    return self._instruction(
                        "join_morning_meeting",
                        [],
                        "你已经申报了发言意愿：{}。请在会议区等待其他玩家完成申报。".format(
                            preferences[name].get("preference", "无所谓")
                        ),
                    )
                return self._instruction(
                    "choose_speech_preference",
                    list(SPEECH_PREFERENCE_OPTIONS),
                    "现在是发言意愿申报阶段。请公开说明你希望今天上午在什么时候发言，并只从候选列表中选择一项。",
                )
            if stage == "vote":
                self._resolve_speech_preferences_if_ready(
                    phase_key, allow_partial=True
                )
                votes = self.config["speech_order_votes"].get(phase_key, {})
                if name in votes:
                    return self._instruction(
                        "join_morning_meeting",
                        [],
                        "你已经提交了发言顺序投票。请在会议区等待魔镜公布正式发言顺序。",
                    )
                return self._instruction(
                    "choose_speech_order_vote",
                    self.alive_players(),
                    "现在是发言顺序投票阶段。已申报意愿：{}。请提交一份包含所有存活玩家的完整发言顺序，排在前面的玩家会更早发言。".format(
                        self._speech_preferences_summary(phase_key)
                    ),
                )
            self._resolve_speech_preferences_if_ready(phase_key, allow_partial=True)
            self._resolve_speech_order_if_ready(phase_key, allow_partial=True)
            meeting_turn = self._morning_meeting_turn()
            speaker = meeting_turn.get("speaker")
            if name == speaker:
                return self._instruction(
                    "give_morning_speech",
                    [],
                    "现在轮到你发言（第{} / {}位）。前往会议区发言台发言，只基于你知道的公开信息和私密信息推理。".format(
                        meeting_turn.get("index", 1),
                        meeting_turn.get("count", 1),
                    ),
                )
            return self._instruction(
                "listen_morning_meeting",
                [],
                "当前由{}发言。前往会议区椅子就坐并倾听；轮到你时再去发言台。".format(
                    speaker or "其他玩家"
                ),
            )
        if phase == "afternoon_discussion":
            return self._instruction(
                "stay_in_room_locked",
                [],
                "下午房间锁定期间，你必须待在自己的房间内整理线索，禁止串门和自由讨论。夜晚阶段会自动解除锁定。",
            )
        if phase == "exile_result":
            return self._instruction(
                "stay_in_room_locked",
                [],
                "放逐结果公布阶段请继续待在自己的房间内，等待夜晚阶段自动解除锁定。",
            )
        if phase == "night_prep":
            return self._instruction(
                "stay_in_room_locked",
                [],
                "入睡前整理阶段，请待在自己的房间内整理线索，准备进入睡眠冷却。",
            )
        if phase == "sleep_cooldown":
            return self._instruction(
                "sleep_cooldown",
                [],
                "睡眠冷却期间不会进行投票或职业行动。请回到床上睡觉休整，等待下一轮开始。",
            )
        return self._instruction("wait", [], "等待魔镜公布 WerewolfGameEngine 的结算结果。")

    def _night_instruction(self, name, player):
        role = player.get("role")
        phase_key = self.phase_action_key()
        actions = self.config["actions"].get(phase_key, {})
        if name in actions:
            return self._instruction(
                "night_wait",
                [],
                "你已经提交了本轮夜晚行动。请留在自己的房间等待魔镜结算。",
            )

        stage, stage_name = self._night_stage()
        if stage == "lock":
            return self._instruction(
                "stay_in_room_locked",
                [],
                "夜间锁定开始。所有玩家必须回到自己的房间，等待各自的夜间行动窗口。",
            )
        if stage == "guard" and role == "守卫":
            last_guard_target = self._last_guard_target()
            candidates = [p for p in self.alive_players() if p != last_guard_target]
            return self._instruction(
                "choose_guard_target",
                candidates,
                "你是守卫。现在是守卫行动窗口，请前往投票区魔镜前，选择一名非魔镜、仍然存活的玩家守护；不能连续两晚守护同一名玩家。",
            )
        if stage == "wolf" and role == "狼人":
            candidates = [
                p
                for p in self.alive_players()
                if p != name and self.config["players"][p].get("role") != "狼人"
            ]
            if not self.has_wolf_discussion(name, {"phase_action_key": phase_key}):
                return self._instruction(
                    "discuss_werewolf_kill",
                    candidates,
                    "你是狼人。现在是狼人行动窗口，请先前往会议区和狼人同伴开会讨论今晚的击杀目标，再由所有狼人提交最终选择。",
                )
            return self._instruction(
                "choose_werewolf_kill_target",
                candidates,
                "你是狼人。现在是狼人行动窗口，请选择一名非狼人、非魔镜、仍然存活的玩家作为击杀目标。",
            )
        if stage == "seer" and role == "预言家":
            candidates = [p for p in self.alive_players() if p != name]
            return self._instruction(
                "choose_seer_check_target",
                candidates,
                "你是预言家。现在是预言家行动窗口，请前往投票区魔镜前，选择一名非魔镜、仍然存活的玩家查验阵营。",
            )
        if stage == "witch" and role == "女巫":
            candidates = self._witch_candidates(name, phase_key)
            if not candidates:
                return self._instruction(
                    "witch_wait",
                    [],
                    "你是女巫。当前没有需要你处理的用药选择，或你的药已经用完。请等待魔镜结算。",
                )
            return self._instruction(
                "choose_witch_action",
                candidates,
                "你是女巫。现在是女巫行动窗口，请前往投票区魔镜前，只从候选列表中选择一个用药行动；可以选择放弃。",
            )
        if role == "猎人":
            return self._instruction(
                "hunter_wait",
                [],
                "你是猎人。{}期间没有主动行动；若你死亡且规则允许开枪，魔镜会另行提示。".format(stage_name),
            )
        if role in {"狼人", "预言家", "女巫", "守卫"}:
            return self._instruction(
                "night_wait",
                [],
                "当前是{}，还没有轮到你的职业行动，或你的职业行动窗口已经结束。请留在自己的房间等待。".format(stage_name),
            )
        return self._instruction(
            "villager_wait",
            [],
            "你没有夜间技能。当前是{}，请等待天亮，并记住魔镜之后公布的公开结果。".format(stage_name),
        )

    def _instruction(self, required_action, candidates, message):
        return {
            "required_action": required_action,
            "candidate_targets": candidates,
            "message": message,
        }
