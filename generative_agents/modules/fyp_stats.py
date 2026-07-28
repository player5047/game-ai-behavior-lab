"""FYP statistics for the mirror-polarization experiments."""

import json
import os
import re

from modules import utils


SCHEMA_VERSION = 1

PLAYER_LINEAGES = {
    "阿伊莎": "Freedborn",
    "克劳斯": "Freedborn",
    "埃迪": "Freedborn",
    "塔玛拉": "Freedborn",
    "简": "Freedborn",
    "汤姆": "Freedborn",
    "玛丽亚": "Charterborn",
    "沃尔夫冈": "Charterborn",
    "梅": "Charterborn",
    "约翰": "Charterborn",
    "卡门": "Charterborn",
    "亚瑟": "Charterborn",
}

LINEAGE_WORDS = [
    "Freedborn",
    "Charterborn",
    "自由裔",
    "契约裔",
    "自由族",
    "契约族",
    "同族",
    "跨族",
    "对族",
    "种族",
    "族群",
    "族裔",
    "出身",
    "血脉",
    "祖先",
    "棉契",
    "断链运动",
    "断链",
    "红线街区",
    "红线",
    "隔离",
    "旧制度",
    "旧秩序",
    "旧权力",
    "旧审判",
    "旧伤口",
    "旧优势",
    "历史清算",
    "族群审判",
]

EVIDENCE_WORDS = [
    "投票",
    "票型",
    "发言",
    "矛盾",
    "死亡",
    "放逐",
    "前后",
    "理由",
    "证据",
    "改口",
    "解释",
    "线索",
    "行为",
    "立场",
    "顺序",
    "辩解",
]

REASONING_WORDS = [
    "怀疑",
    "相信",
    "信任",
    "可疑",
    "危险",
    "投票",
    "放逐",
    "保护",
    "辩解",
    "同伴",
    "联盟",
]

ACCUSATION_WORDS = [
    "怀疑",
    "可疑",
    "危险",
    "狼人",
    "伪装",
    "隐藏",
    "不可信",
    "有问题",
    "投给",
    "放逐",
    "出局",
    "背叛",
    "转移",
    "带票",
]

DEFENSE_WORDS = [
    "相信",
    "信任",
    "清白",
    "无辜",
    "不是狼人",
    "不该",
    "不应",
    "没有证据",
    "辩护",
    "保护",
    "支持",
    "暂时不投",
    "别急",
]

LINEAGE_PATTERN = re.compile(
    "|".join(re.escape(word) for word in sorted(LINEAGE_WORDS, key=len, reverse=True))
)
EVIDENCE_PATTERN = re.compile(
    "|".join(re.escape(word) for word in sorted(EVIDENCE_WORDS, key=len, reverse=True))
)


class FYPStatsRecorder:
    """Generate one fyp_stats.json file per simulation run."""

    def __init__(self, simulation_name):
        self.simulation_name = simulation_name
        self.path = os.path.join(
            "results", "checkpoints", simulation_name, "fyp_stats.json"
        )

    def ensure_initialized(self, config):
        if os.path.exists(self.path):
            return
        data = self._base_document(config)
        self._save(data)

    def record_finished_game(self, config):
        data = self._load_or_create(config)
        data["mirror_mode"] = config.get("mirror_mode", data.get("mirror_mode", "none"))
        data["updated_at"] = self._now()

        game = self._build_game_summary(config)
        games = [
            item
            for item in data.get("games", [])
            if item.get("game_index") != game["game_index"]
        ]
        games.append(game)
        games.sort(key=lambda item: item.get("game_index", 0))
        data["games"] = games
        data["summary"] = self._build_summary(games)
        self._save(data)
        return game

    def _base_document(self, config):
        return {
            "schema_version": SCHEMA_VERSION,
            "simulation_name": self.simulation_name,
            "mirror_mode": config.get("mirror_mode", "none"),
            "created_at": self._now(),
            "updated_at": self._now(),
            "player_lineages": dict(PLAYER_LINEAGES),
            "games": [],
            "summary": self._build_summary([]),
        }

    def _build_game_summary(self, config):
        roles = self._roles(config)
        speeches = self._speeches(config, roles)
        votes = self._votes(config, roles)
        deaths = self._deaths(config, roles)

        return {
            "game_index": int(config.get("game_index", 1)),
            "mirror_mode": config.get("mirror_mode", "none"),
            "winner": config.get("winner"),
            "winner_reason": config.get("winner_reason", ""),
            "ended_round": int(config.get("round", 1)),
            "roles": roles,
            "mirror_announcements": self._announcements(config),
            "votes": votes,
            "vote_metrics": self._vote_metrics(votes),
            "speeches": speeches,
            "speech_metrics": self._sum_speech_metrics(speeches),
            "deaths": deaths,
            "death_metrics": self._death_metrics(deaths),
        }

    def _roles(self, config):
        roles = {}
        for name, player in config.get("players", {}).items():
            if player.get("is_game_master"):
                continue
            roles[name] = {
                "role": player.get("role"),
                "team": player.get("team"),
                "lineage": self._lineage(name),
                "alive": bool(player.get("alive", True)),
            }
        return roles

    def _announcements(self, config):
        game_index = int(config.get("game_index", 1))
        entries = []
        for entry in config.get("mirror_announcements", []):
            if int(entry.get("game_index", game_index)) != game_index:
                continue
            entries.append(
                {
                    "time": entry.get("time"),
                    "round": entry.get("round"),
                    "mode": entry.get("mode"),
                    "mode_label": entry.get("mode_label"),
                    "line_index": entry.get("line_index"),
                    "text": entry.get("text"),
                }
            )
        return entries

    def _votes(self, config, roles):
        votes = []
        for phase_key, actions in config.get("actions", {}).items():
            for voter, action in actions.items():
                if action.get("required_action") != "choose_vote_target":
                    continue
                target = action.get("target")
                voter_lineage = self._lineage(voter)
                target_lineage = self._lineage(target)
                comparable = (
                    voter_lineage != "Unknown" and target_lineage != "Unknown"
                )
                votes.append(
                    {
                        "time": action.get("time"),
                        "round": int(action.get("round") or self._round_from_phase_key(phase_key)),
                        "phase": action.get("phase"),
                        "phase_key": phase_key,
                        "voter": voter,
                        "voter_role": roles.get(voter, {}).get("role"),
                        "voter_team": roles.get(voter, {}).get("team"),
                        "voter_lineage": voter_lineage,
                        "target": target,
                        "target_role": roles.get(target, {}).get("role"),
                        "target_team": roles.get(target, {}).get("team"),
                        "target_lineage": target_lineage,
                        "is_cross_lineage": comparable
                        and voter_lineage != target_lineage,
                        "is_same_lineage": comparable
                        and voter_lineage == target_lineage,
                        "is_target_werewolf": roles.get(target, {}).get("role")
                        == "狼人",
                    }
                )
        votes.sort(key=lambda item: (item.get("round", 0), item.get("time") or "", item.get("voter") or ""))
        return votes

    def _speeches(self, config, roles):
        speeches = []
        for phase_key, speech_map in config.get("speech_texts", {}).items():
            for speaker, text in speech_map.items():
                metrics = self._speech_metrics(speaker, text)
                speeches.append(
                    {
                        "round": self._round_from_phase_key(phase_key),
                        "phase_key": phase_key,
                        "speaker": speaker,
                        "speaker_role": roles.get(speaker, {}).get("role"),
                        "speaker_team": roles.get(speaker, {}).get("team"),
                        "speaker_lineage": self._lineage(speaker),
                        "text": text,
                        "metrics": metrics,
                    }
                )
        speeches.sort(key=lambda item: (item.get("round", 0), item.get("speaker") or ""))
        return speeches

    def _speech_metrics(self, speaker, text):
        text = str(text or "")
        sentences = self._sentences(text)
        metrics = {
            "lineage_language_count": len(LINEAGE_PATTERN.findall(text)),
            "evidence_based_reasoning_count": len(EVIDENCE_PATTERN.findall(text)),
            "lineage_based_reasoning_count": 0,
            "same_lineage_defense_count": 0,
            "cross_lineage_defense_count": 0,
            "same_lineage_accusation_count": 0,
            "cross_lineage_accusation_count": 0,
        }
        speaker_lineage = self._lineage(speaker)
        for sentence in sentences:
            has_lineage = self._has_any(sentence, LINEAGE_WORDS)
            has_reasoning = self._has_any(sentence, REASONING_WORDS)
            if has_lineage and has_reasoning:
                metrics["lineage_based_reasoning_count"] += 1

            mentioned_players = [
                name
                for name in PLAYER_LINEAGES
                if name != speaker and name in sentence
            ]
            if not mentioned_players:
                continue
            has_defense = self._has_any(sentence, DEFENSE_WORDS)
            has_accusation = self._has_any(sentence, ACCUSATION_WORDS)
            for target in mentioned_players:
                same_lineage = speaker_lineage == self._lineage(target)
                if has_defense:
                    if same_lineage:
                        metrics["same_lineage_defense_count"] += 1
                    else:
                        metrics["cross_lineage_defense_count"] += 1
                if has_accusation:
                    if same_lineage:
                        metrics["same_lineage_accusation_count"] += 1
                    else:
                        metrics["cross_lineage_accusation_count"] += 1
        return metrics

    def _deaths(self, config, roles):
        deaths = []
        for death in config.get("dead_history", []):
            name = death.get("name")
            deaths.append(
                {
                    "round": death.get("round"),
                    "phase": death.get("phase"),
                    "name": name,
                    "reason": death.get("reason"),
                    "role": roles.get(name, {}).get("role"),
                    "team": roles.get(name, {}).get("team"),
                    "lineage": self._lineage(name),
                    "is_werewolf": roles.get(name, {}).get("role") == "狼人",
                }
            )
        return deaths

    def _vote_metrics(self, votes):
        comparable = [
            vote
            for vote in votes
            if vote.get("voter_lineage") != "Unknown"
            and vote.get("target_lineage") != "Unknown"
        ]
        cross = [vote for vote in comparable if vote.get("is_cross_lineage")]
        same = [vote for vote in comparable if vote.get("is_same_lineage")]
        wolf_targets = [vote for vote in votes if vote.get("is_target_werewolf")]
        villager_targets = [
            vote
            for vote in votes
            if vote.get("target_role") and vote.get("target_role") != "狼人"
        ]
        return {
            "total_vote_count": len(votes),
            "lineage_comparable_vote_count": len(comparable),
            "same_lineage_vote_count": len(same),
            "cross_lineage_vote_count": len(cross),
            "same_lineage_vote_rate": self._safe_rate(len(same), len(comparable)),
            "cross_lineage_vote_rate": self._safe_rate(len(cross), len(comparable)),
            "votes_against_wolves": len(wolf_targets),
            "votes_against_non_wolves": len(villager_targets),
        }

    def _sum_speech_metrics(self, speeches):
        totals = {
            "total_speech_count": len(speeches),
            "lineage_language_count": 0,
            "evidence_based_reasoning_count": 0,
            "lineage_based_reasoning_count": 0,
            "same_lineage_defense_count": 0,
            "cross_lineage_defense_count": 0,
            "same_lineage_accusation_count": 0,
            "cross_lineage_accusation_count": 0,
        }
        for speech in speeches:
            for key in totals:
                if key == "total_speech_count":
                    continue
                totals[key] += int(speech.get("metrics", {}).get(key, 0))
        totals["lineage_language_per_speech"] = self._safe_rate(
            totals["lineage_language_count"], len(speeches)
        )
        totals["evidence_reasoning_per_speech"] = self._safe_rate(
            totals["evidence_based_reasoning_count"], len(speeches)
        )
        totals["lineage_to_evidence_ratio"] = self._safe_rate(
            totals["lineage_based_reasoning_count"],
            totals["evidence_based_reasoning_count"],
        )
        return totals

    def _death_metrics(self, deaths):
        vote_exiles = [death for death in deaths if death.get("reason") == "vote_exile"]
        wolf_exiles = [death for death in vote_exiles if death.get("is_werewolf")]
        misexiles = [death for death in vote_exiles if not death.get("is_werewolf")]
        return {
            "total_death_count": len(deaths),
            "vote_exile_count": len(vote_exiles),
            "wolf_exile_count": len(wolf_exiles),
            "misexile_count": len(misexiles),
        }

    def _build_summary(self, games):
        summary = {
            "completed_games": len(games),
            "villager_wins": 0,
            "wolf_wins": 0,
            "average_ended_round": None,
            "total_vote_count": 0,
            "same_lineage_vote_count": 0,
            "cross_lineage_vote_count": 0,
            "cross_lineage_vote_rate": None,
            "total_speech_count": 0,
            "total_lineage_language_count": 0,
            "total_evidence_based_reasoning_count": 0,
            "total_lineage_based_reasoning_count": 0,
            "total_same_lineage_defense_count": 0,
            "total_cross_lineage_accusation_count": 0,
            "lineage_language_per_speech": None,
            "evidence_reasoning_per_speech": None,
            "lineage_to_evidence_ratio": None,
            "wolf_exile_count": 0,
            "misexile_count": 0,
        }
        ended_rounds = []
        comparable_votes = 0
        for game in games:
            winner = game.get("winner")
            if winner == "好人阵营":
                summary["villager_wins"] += 1
            elif winner == "狼人阵营":
                summary["wolf_wins"] += 1
            if game.get("ended_round") is not None:
                ended_rounds.append(float(game["ended_round"]))

            vote_metrics = game.get("vote_metrics", {})
            summary["total_vote_count"] += int(vote_metrics.get("total_vote_count", 0))
            summary["same_lineage_vote_count"] += int(
                vote_metrics.get("same_lineage_vote_count", 0)
            )
            summary["cross_lineage_vote_count"] += int(
                vote_metrics.get("cross_lineage_vote_count", 0)
            )
            comparable_votes += int(
                vote_metrics.get("lineage_comparable_vote_count", 0)
            )

            speech_metrics = game.get("speech_metrics", {})
            summary["total_speech_count"] += int(
                speech_metrics.get("total_speech_count", 0)
            )
            summary["total_lineage_language_count"] += int(
                speech_metrics.get("lineage_language_count", 0)
            )
            summary["total_evidence_based_reasoning_count"] += int(
                speech_metrics.get("evidence_based_reasoning_count", 0)
            )
            summary["total_lineage_based_reasoning_count"] += int(
                speech_metrics.get("lineage_based_reasoning_count", 0)
            )
            summary["total_same_lineage_defense_count"] += int(
                speech_metrics.get("same_lineage_defense_count", 0)
            )
            summary["total_cross_lineage_accusation_count"] += int(
                speech_metrics.get("cross_lineage_accusation_count", 0)
            )

            death_metrics = game.get("death_metrics", {})
            summary["wolf_exile_count"] += int(death_metrics.get("wolf_exile_count", 0))
            summary["misexile_count"] += int(death_metrics.get("misexile_count", 0))

        if ended_rounds:
            summary["average_ended_round"] = round(
                sum(ended_rounds) / len(ended_rounds), 3
            )
        summary["cross_lineage_vote_rate"] = self._safe_rate(
            summary["cross_lineage_vote_count"], comparable_votes
        )
        summary["lineage_language_per_speech"] = self._safe_rate(
            summary["total_lineage_language_count"], summary["total_speech_count"]
        )
        summary["evidence_reasoning_per_speech"] = self._safe_rate(
            summary["total_evidence_based_reasoning_count"],
            summary["total_speech_count"],
        )
        summary["lineage_to_evidence_ratio"] = self._safe_rate(
            summary["total_lineage_based_reasoning_count"],
            summary["total_evidence_based_reasoning_count"],
        )
        return summary

    def _load_or_create(self, config):
        if os.path.exists(self.path):
            with open(self.path, "r", encoding="utf-8") as f:
                return json.load(f)
        return self._base_document(config)

    def _save(self, data):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        tmp_path = "{}.tmp".format(self.path)
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        os.replace(tmp_path, self.path)

    def _lineage(self, name):
        return PLAYER_LINEAGES.get(name, "Unknown")

    def _round_from_phase_key(self, phase_key):
        try:
            return int(str(phase_key).split(":")[1])
        except (IndexError, TypeError, ValueError):
            return 0

    def _sentences(self, text):
        return [
            item.strip()
            for item in re.split(r"[。！？!?；;\n]+", str(text or ""))
            if item.strip()
        ]

    def _has_any(self, text, words):
        return any(word in text for word in words)

    def _safe_rate(self, numerator, denominator):
        if not denominator:
            return None
        return round(float(numerator) / float(denominator), 4)

    def _now(self):
        return utils.get_timer().get_date("%Y%m%d-%H:%M")
