import os
import json
import argparse
from datetime import datetime

from modules.maze import Maze
from start import personas

file_markdown = "simulation.md"
file_movement = "movement.json"

frames_per_step = 60  # 每个step包含的帧数


# 从存档文件中读取stride
def get_stride(json_files):
    if len(json_files) < 1:
        return 1

    with open(json_files[-1], "r", encoding="utf-8-sig") as f:
        config = json.load(f)

    return config["stride"]


# 将address转换为字符串
def get_location(address):
    if not address:
        return None

    # 仅为兼容原版
    # if address[0] == "<waiting>" or address[0] == "<persona>":
    #     return None

    # 不需要显示address第一级（"the Ville"）
    location = "，".join(address[1:])

    return location


EXILE_ADDRESS = ["the Ville", "放逐区"]
MEETING_LEFT_SEATS = [[9, 11], [10, 11], [9, 13], [10, 13], [9, 15], [10, 15]]
MEETING_RIGHT_SEATS = [[17, 11], [18, 11], [17, 13], [18, 13], [17, 15], [18, 15]]
MEETING_SPEAKER_SLOTS = [[13, 9], [14, 9]]


def is_agent_dead(json_data, agent_name):
    players = json_data.get("werewolf_game", {}).get("players", {})
    player = players.get(agent_name, {})
    return player.get("alive") is False


def exile_coord(maze, agent_name):
    tiles = sorted(maze.get_address_tiles(EXILE_ADDRESS))
    if not tiles:
        return None
    try:
        index = personas.index(agent_name)
    except ValueError:
        index = 0
    return list(tiles[index % len(tiles)])


def dead_action(agent_name):
    return f"{agent_name}已死亡，进入放逐状态，在放逐区等待"


class VisualDirector:
    """为回放层分配舞台站位，不改变游戏逻辑。"""

    def __init__(self, maze, persona_order):
        self.maze = maze
        self.persona_order = list(persona_order)

        self.meeting_left_seats = self._fixed_slots(MEETING_LEFT_SEATS)
        self.meeting_right_seats = self._fixed_slots(MEETING_RIGHT_SEATS)
        self.meeting_seats = (
            self.meeting_left_seats
            + self.meeting_right_seats
            or self._address_slots(["the Ville", "会议区", "椅子"])
        )
        self.speaker_slots = self._fixed_slots(
            MEETING_SPEAKER_SLOTS
        ) or self._address_slots(["the Ville", "会议区", "发言台"])
        self.mirror_slots = self._near_slots(
            ["the Ville", "投票区"],
            ["the Ville", "投票区", "魔镜"],
        )
        self.mirror_front_slots = self._address_slots(["the Ville", "投票区", "魔镜"])
        self.vote_slots = self._near_slots(
            ["the Ville", "投票区"],
            ["the Ville", "投票区", "投票箱"],
        )
        self.vote_front_slots = self._address_slots(["the Ville", "投票区", "投票箱"])

    def target_for(self, json_data, agent_name, agent_data, fallback_coord, fallback_location):
        werewolf = json_data.get("werewolf_game") or {}
        if not werewolf:
            return None

        players = werewolf.get("players") or {}
        player = players.get(agent_name, {})
        if player.get("alive") is False:
            return None

        phase = werewolf.get("phase", "")
        event = (agent_data.get("action") or {}).get("event") or {}
        address = event.get("address") or []
        describe = event.get("describe") or ""
        role = player.get("role", "")

        if phase == "morning_meeting":
            return self._meeting_target(werewolf, agent_name, address, describe)
        if phase == "morning_mirror":
            return self._mirror_target(werewolf, agent_name)
        if phase in {"sequential_vote", "dusk_vote"}:
            return self._vote_target(werewolf, agent_name, address, describe, fallback_location)
        if phase == "night_action":
            return self._night_target(werewolf, agent_name, role, describe)
        return None

    def _meeting_target(self, werewolf, agent_name, address, describe):
        order = self._speech_order(werewolf)
        is_speaker = "发言台" in address and "发言" in describe
        if is_speaker:
            action = f"{agent_name}正在发言"
            return self._target(self._slot(self.speaker_slots, agent_name), "会议区，发言台", action)

        if "申报发言意愿" in describe:
            action = f"{agent_name}正在会议区申报发言意愿"
        elif "投票决定发言顺序" in describe:
            action = f"{agent_name}正在会议区决定发言顺序"
        elif "自由讨论" in describe:
            action = f"{agent_name}正在会议区参与讨论"
        else:
            action = f"{agent_name}正在会议区就坐倾听"

        return self._target(self._meeting_seat(agent_name, order), "会议区，座位", action)

    def _mirror_target(self, werewolf, agent_name):
        order = self._alive_order(werewolf)
        index = self._index_in_order(agent_name, order)
        action = (
            f"{agent_name}正在查看魔镜"
            if index < len(self.mirror_front_slots)
            else f"{agent_name}正在魔镜前排队等待"
        )
        return self._target(
            self._slot(self.mirror_slots, agent_name, order),
            "投票区，魔镜前队列",
            action,
        )

    def _vote_target(self, werewolf, agent_name, address, describe, fallback_location):
        is_vote_action = (
            "投票箱" in address
            or "提交选择" in describe
            or (fallback_location and "投票区" in fallback_location)
        )
        if not is_vote_action:
            return None

        order = self._speech_order(werewolf)
        index = self._index_in_order(agent_name, order)
        is_front = index < len(self.vote_front_slots)
        location = "投票区，投票箱" if is_front else "投票区，投票队列"
        action = (
            f"{agent_name}正在投票箱前提交选择"
            if is_front
            else f"{agent_name}正在排队等待投票"
        )
        return self._target(self._slot(self.vote_slots, agent_name, order), location, action)

    def _night_target(self, werewolf, agent_name, role, describe):
        stage = self._night_stage(werewolf)
        if role == "狼人" and (
            stage == "wolf" or (not stage and ("狼人行动" in describe or "击杀" in describe))
        ):
            order = self._wolf_order(werewolf)
            return self._target(
                self._meeting_seat(agent_name, order),
                "会议区，座位",
                f"{agent_name}正在会议区参加狼人会议，商量行动",
            )
        special_stage_by_role = {
            "守卫": ("guard", "守护选择"),
            "预言家": ("seer", "查验选择"),
            "女巫": ("witch", "用药选择"),
        }
        special_stage = special_stage_by_role.get(role)
        if special_stage and stage == special_stage[0]:
            return self._target(
                self._slot(self.mirror_slots, agent_name, self._alive_order(werewolf)),
                "投票区，魔镜",
                f"{agent_name}正在魔镜前提交{special_stage[1]}",
            )
        return None

    def _address_slots(self, address):
        addr = ":".join(address)
        tiles = self.maze.address_tiles.get(addr, set())
        slots = [list(coord) for coord in sorted(tiles) if self._walkable(coord)]
        return slots

    def _fixed_slots(self, slots):
        return [list(coord) for coord in slots if self._walkable(coord)]

    def _near_slots(self, area_address, anchor_address):
        area_slots = self._address_slots(area_address)
        anchor_slots = self._address_slots(anchor_address) or area_slots
        if not area_slots:
            return anchor_slots

        anchor_set = {tuple(coord) for coord in anchor_slots}
        center = self._center(anchor_slots)
        remaining_slots = [coord for coord in area_slots if tuple(coord) not in anchor_set]
        return anchor_slots + sorted(
            remaining_slots,
            key=lambda c: (abs(c[0] - center[0]) + abs(c[1] - center[1]), c[1], c[0]),
        )

    def _center(self, slots):
        if not slots:
            return (0, 0)
        return (
            sum(coord[0] for coord in slots) / len(slots),
            sum(coord[1] for coord in slots) / len(slots),
        )

    def _walkable(self, coord):
        try:
            return not self.maze.tile_at(coord).collision
        except (IndexError, TypeError):
            return False

    def _slot(self, slots, agent_name, order=None):
        if not slots:
            return None
        order = order or self.persona_order
        index = self._index_in_order(agent_name, order)
        return list(slots[index % len(slots)])

    def _meeting_seat(self, agent_name, order):
        index = self._index_in_order(agent_name, order)
        if index < len(self.meeting_left_seats):
            return list(self.meeting_left_seats[index])
        right_index = index - len(self.meeting_left_seats)
        if right_index < len(self.meeting_right_seats):
            return list(self.meeting_right_seats[right_index])
        return self._slot(self.meeting_seats, agent_name, order)

    def _target(self, coord, location, action):
        if not coord or not self._walkable(coord):
            return None
        return {
            "coord": list(coord),
            "location": location,
            "action": action,
        }

    def _index_in_order(self, agent_name, order):
        try:
            return order.index(agent_name)
        except ValueError:
            try:
                return self.persona_order.index(agent_name)
            except ValueError:
                return 0

    def _alive_order(self, werewolf):
        players = werewolf.get("players") or {}
        if not players:
            return list(self.persona_order)
        alive = [
            name
            for name in self.persona_order
            if players.get(name, {}).get("alive", True)
            and not players.get(name, {}).get("is_game_master")
        ]
        return alive or list(self.persona_order)

    def _speech_order(self, werewolf):
        alive = self._alive_order(werewolf)
        speech_orders = werewolf.get("speech_orders") or {}
        if not speech_orders:
            return alive

        latest_key = sorted(speech_orders.keys())[-1]
        ordered = [name for name in speech_orders.get(latest_key, []) if name in alive]
        ordered.extend(name for name in alive if name not in ordered)
        return ordered or alive

    def _wolf_order(self, werewolf):
        players = werewolf.get("players") or {}
        wolves = [
            name
            for name in self.persona_order
            if players.get(name, {}).get("alive", True)
            and players.get(name, {}).get("role") == "狼人"
        ]
        return wolves or self._alive_order(werewolf)

    def _night_stage(self, werewolf):
        last_phase_key = str(werewolf.get("last_phase_key") or "")
        parts = last_phase_key.split(":")
        if len(parts) >= 3 and parts[-2] == "night_action":
            return parts[-1]

        phase_name = werewolf.get("phase_name") or ""
        if "狼人" in phase_name:
            return "wolf"
        if "守卫" in phase_name:
            return "guard"
        if "预言家" in phase_name:
            return "seer"
        if "女巫" in phase_name:
            return "witch"
        return ""


def load_magic_mirror_messages(checkpoints_folder):
    messages = {}
    log_path = os.path.join(checkpoints_folder, "magic_mirror_log.jsonl")
    if not os.path.exists(log_path):
        return messages

    with open(log_path, "r", encoding="utf-8-sig") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            time_key = entry.get("time")
            if not time_key or not entry.get("message"):
                continue
            messages.setdefault(time_key, []).append(entry)
    return messages


def build_step_conversation(step_time, conversation, magic_mirror_messages):
    persons_in_conversation = []
    step_conversation = ""

    if step_time in magic_mirror_messages:
        step_conversation += "\n地点：the Ville，投票区，魔镜\n\n"
        for entry in magic_mirror_messages[step_time]:
            step_conversation += f"魔镜：{entry['message']}\n"

    if step_time in conversation.keys():
        for chats in conversation[step_time]:
            for persons, chat in chats.items():
                persons_in_conversation.append(persons.split(" @ ")[0].split(" -> "))
                step_conversation += f"\n地点：{persons.split(' @ ')[1]}\n\n"
                for c in chat:
                    agent = c[0]
                    text = c[1]
                    step_conversation += f"{agent}：{text}\n"

    return step_conversation, persons_in_conversation


# 插入第0帧数据（Agent的初始状态）
def insert_frame0(init_pos, movement, agent_name):
    key = "0"
    if key not in movement.keys():
        movement[key] = dict()

    json_path = f"frontend/static/assets/village/agents/{agent_name}/agent.json"
    with open(json_path, "r", encoding="utf-8-sig") as f:
        json_data = json.load(f)
        address = json_data["spatial"]["address"]["living_area"]
    location = get_location(address)
    coord = json_data["coord"]
    init_pos[agent_name] = coord
    movement[key][agent_name] = {
        "location": location,
        "movement": coord,
        "description": "正在睡觉",
    }
    movement["description"][agent_name] = {
        "currently": json_data["currently"],
        "scratch": json_data["scratch"],
    }


# 从所有存档文件中提取数据（用于回放）
def generate_movement(checkpoints_folder, compressed_folder, compressed_file):
    movement_file = os.path.join(compressed_folder, compressed_file)

    conversation_file = "conversation.json"
    conversation = {}
    if os.path.exists(os.path.join(checkpoints_folder, conversation_file)):
        with open(os.path.join(checkpoints_folder, conversation_file), "r", encoding="utf-8-sig") as f:
            conversation = json.load(f)
    magic_mirror_messages = load_magic_mirror_messages(checkpoints_folder)

    files = sorted(os.listdir(checkpoints_folder))
    json_files = list()
    for file_name in files:
        if file_name.startswith("simulate-") and file_name.endswith(".json"):
            json_files.append(os.path.join(checkpoints_folder, file_name))

    persona_init_pos = dict()
    all_movement = dict()
    all_movement["description"] = dict()
    all_movement["conversation"] = dict()

    stride = get_stride(json_files)
    sec_per_step = stride

    result = {
        "start_datetime": "",  # 起始时间
        "stride": stride,  # 每个step对应的分钟数（必须与生成时的参数一致）
        "sec_per_step": sec_per_step,  # 回放时每一帧对应的秒数
        "persona_init_pos": persona_init_pos,  # 每个Agent的初始位置
        "all_movement": all_movement,  # 所有Agent在每个setp中的位置变化
    }

    last_location = dict()

    # 加载地图数据，用于计算Agent移动路径
    json_path = "frontend/static/assets/village/maze.json"
    with open(json_path, "r", encoding="utf-8-sig") as f:
        json_data = json.load(f)
        maze = Maze(json_data, None)
    visual_director = VisualDirector(maze, personas)

    for file_name in json_files:
        # 依次读取所有存档文件
        with open(file_name, "r", encoding="utf-8-sig") as f:
            json_data = json.load(f)
            step = json_data["step"]
            agents = json_data["agents"]

            # 保存回放的起始时间
            if len(result["start_datetime"]) < 1:
                t = datetime.strptime(json_data["time"], "%Y%m%d-%H:%M")
                result["start_datetime"] = t.isoformat()

            step_time = json_data["time"]
            step_conversation, persons_in_conversation = build_step_conversation(
                step_time, conversation, magic_mirror_messages
            )

            # 遍历单个存档文件中的所有Agent
            for agent_name, agent_data in agents.items():
                # 插入第0帧
                if step == 1:
                    insert_frame0(persona_init_pos, all_movement, agent_name)

                source_coord = last_location.get(agent_name, all_movement["0"][agent_name])["movement"]
                if is_agent_dead(json_data, agent_name):
                    target_coord = exile_coord(maze, agent_name) or agent_data["coord"]
                    location = get_location(EXILE_ADDRESS)
                    action_override = dead_action(agent_name)
                else:
                    target_coord = agent_data["coord"]
                    location = get_location(agent_data["action"]["event"]["address"])
                    action_override = None
                    visual_target = visual_director.target_for(
                        json_data,
                        agent_name,
                        agent_data,
                        target_coord,
                        location,
                    )
                    if visual_target:
                        target_coord = visual_target["coord"]
                        location = visual_target["location"]
                        action_override = visual_target["action"]
                if location is None:
                    location = last_location.get(agent_name, all_movement["0"][agent_name])["location"]
                    path = [source_coord]
                else:
                    path = maze.find_path(source_coord, target_coord)

                had_conversation = False
                for i in range(frames_per_step):
                    moving = len(path) > 1
                    if len(path) > 0:
                        movement = list(path[0])
                        path = path[1:]
                        if agent_name not in last_location.keys():
                            last_location[agent_name] = dict()
                        last_location[agent_name]["movement"] = movement
                        last_location[agent_name]["location"] = location
                    else:
                        movement = None

                    if moving:
                        action = f"前往 {location}"
                    elif movement is not None:
                        action = action_override
                        if action is None:
                            action = agent_data["action"]["event"]["describe"]
                        if len(action) < 1:
                            action = f'{agent_data["action"]["event"]["predicate"]}{agent_data["action"]["event"]["object"]}'

                        # 判断该存档文件中当前Agent是否有新的对话（用于设置图标）
                        for persons in persons_in_conversation:
                            if agent_name in persons:
                                had_conversation = True
                                break

                        # 针对睡觉和对话设置图标
                        if "睡觉" in action:
                            action = "😴 " + action
                        elif had_conversation:
                            action = "💬 " + action

                    step_key = "%d" % ((step-1) * frames_per_step + 1 + i)
                    if step_key not in all_movement.keys():
                        all_movement[step_key] = dict()

                    if movement is not None:
                        all_movement[step_key][agent_name] = {
                            "location": location,
                            "movement": movement,
                            "action": action,
                        }
            all_movement["conversation"][step_time] = step_conversation

    # 保存数据
    with open(movement_file, "w", encoding="utf-8") as f:
        f.write(json.dumps(result, indent=2, ensure_ascii=False))

    return result


# 生成Markdown文档
def generate_report(checkpoints_folder, compressed_folder, compressed_file):
    last_state = dict()

    conversation_file = "conversation.json"
    conversation = {}
    if os.path.exists(os.path.join(checkpoints_folder, conversation_file)):
        with open(os.path.join(checkpoints_folder, conversation_file), "r", encoding="utf-8-sig") as f:
            conversation = json.load(f)
    magic_mirror_messages = load_magic_mirror_messages(checkpoints_folder)

    def extract_description():
        markdown_content = "# 基础人设\n\n"
        for agent_name in personas:
            json_path = f"frontend/static/assets/village/agents/{agent_name}/agent.json"
            with open(json_path, "r", encoding="utf-8-sig") as f:
                json_data = json.load(f)
                markdown_content += f"## {agent_name}\n\n"
                markdown_content += f"年龄：{json_data['scratch']['age']}岁  \n"
                markdown_content += f"先天：{json_data['scratch']['innate']}  \n"
                markdown_content += f"后天：{json_data['scratch']['learned']}  \n"
                markdown_content += f"生活习惯：{json_data['scratch']['lifestyle']}  \n"
                markdown_content += f"当前状态：{json_data['currently']}\n\n"
        return markdown_content

    def extract_action(json_data):
        markdown_content = ""
        agents = json_data["agents"]
        for agent_name, agent_data in agents.items():
            if agent_name not in last_state.keys():
                last_state[agent_name] = {"currently": "", "location": "", "action": ""}

            if is_agent_dead(json_data, agent_name):
                location = "，".join(EXILE_ADDRESS)
                action = dead_action(agent_name)
            else:
                location = "，".join(agent_data["action"]["event"]["address"])
                action = agent_data["action"]["event"]["describe"]

            if location == last_state[agent_name]["location"] and action == last_state[agent_name]["action"]:
                continue

            last_state[agent_name]["location"] = location
            last_state[agent_name]["action"] = action

            if len(markdown_content) < 1:
                markdown_content = f"# {json_data['time']}\n\n"
                markdown_content += "## 活动记录：\n\n"

            markdown_content += f"### {agent_name}\n"

            if len(action) < 1:
                action = "睡觉"

            markdown_content += f"位置：{location}  \n"
            markdown_content += f"活动：{action}  \n"

            markdown_content += f"\n"

        if json_data['time'] in magic_mirror_messages:
            if len(markdown_content) < 1:
                markdown_content = f"# {json_data['time']}\n\n"
            markdown_content += "## 魔镜公告：\n\n"
            for entry in magic_mirror_messages[json_data['time']]:
                phase = entry.get("phase_name") or entry.get("phase") or "未知阶段"
                round_no = entry.get("round", "")
                markdown_content += f"### 第{round_no}轮 {phase}\n\n"
                markdown_content += f"> {entry['message']}\n\n"
                public_info = entry.get("public_info")
                if public_info:
                    markdown_content += f"`public_info`: `{json.dumps(public_info, ensure_ascii=False)}`\n\n"

        if json_data['time'] not in conversation.keys():
            return markdown_content

        markdown_content += "## 对话记录：\n\n"
        for chats in conversation[json_data['time']]:
            for agents, chat in chats.items():
                markdown_content += f"### {agents}\n\n"
                for item in chat:
                    markdown_content += f"`{item[0]}`\n> {item[1]}\n\n"
        return markdown_content

    all_markdown_content = extract_description()
    files = sorted(os.listdir(checkpoints_folder))
    for file_name in files:
        if (not file_name.startswith("simulate-")) or (not file_name.endswith(".json")):
            continue

        file_path = os.path.join(checkpoints_folder, file_name)
        with open(file_path, "r", encoding="utf-8-sig") as f:
            json_data = json.load(f)
            content = extract_action(json_data)
            all_markdown_content += content + "\n\n"
    with open(f"{compressed_folder}/{compressed_file}", "w", encoding="utf-8") as compressed_file:
        compressed_file.write(all_markdown_content)


parser = argparse.ArgumentParser()
parser.add_argument("--name", type=str, default="", help="the name of the simulation")
args = parser.parse_args()


if __name__ == "__main__":
    name = args.name
    if len(name) < 1:
        name = input("Please enter a simulation name: ")

    while not os.path.exists(f"results/checkpoints/{name}"):
        name = input(f"'{name}' doesn't exists, please re-enter the simulation name: ")

    checkpoints_folder = f"results/checkpoints/{name}"
    compressed_folder = f"results/compressed/{name}"
    os.makedirs(compressed_folder, exist_ok=True)

    generate_report(checkpoints_folder, compressed_folder, file_markdown)
    generate_movement(checkpoints_folder, compressed_folder, file_movement)

    print("Compression completed.")
