# -*- coding: utf-8 -*-
"""
smoke_generator.py
烟雾团逐步生成模块，提供 SmokeGenerator 类及全局便捷函数。
以中心点为圆心，可分别指定首次延迟和圈间间隔，直到整个球体生成完成。
支持多个烟雾同时生成，互不干扰。
可自定义填充的方块标识符（默认 "fangyu:smoke"）。
支持生成完成后自动从外向内逐层清除方块（可选），清除间隔和延迟可配置。
"""
import server.extraServerApi as serverApi
import time
import random
import FangyuData


class SmokeGenerator(object):
    """
    烟雾生成器类，管理多个烟雾任务。
    """

    def __init__(self):
        # 存储所有进行中的烟雾任务，key为任务ID，value为任务状态字典
        self._smoke_tasks = {}

    def comp_smoke(self, args):
        """
        生成烟雾的主方法。

        :param args: dict，包含以下键：
            - "id"              : 方块操作组件ID（必填）
            - "pos"             : 坐标元组 (x, y, z)（必填）
            - "dimensionId"     : 维度ID（必填）
            - "dispersed_value" : 烟雾扩散系数，决定半径（必填）
            - "block_name"      : 要放置的方块标识符（可选，默认 "fangyu:smoke"）
            - "levelId"         : 世界ID，用于定时器（可选，默认0）
            - "initial_delay"   : 第一次生成前的延迟秒数（可选，默认0.0）
            - "interval_delay"  : 后续每圈之间的间隔秒数（可选，默认3.0）
            - "delay"           : 旧参数兼容，若提供且未提供 interval_delay，则 interval_delay = delay，
                                  且 initial_delay = delay 以保持原有行为
            - "clear_enabled"   : 是否启用自动清除（可选，默认 False）
            - "clear_delay"     : 生成完成后延迟多少秒开始清除（可选，默认 0.0）
            - "clear_interval"  : 清除每层之间的间隔秒数（可选，默认等于 interval_delay）
        """
        # 生成唯一任务ID
        base_id = args.get("id", "default")
        task_id = str(base_id)
        while task_id in self._smoke_tasks and not self._smoke_tasks[task_id]['finished']:
            task_id = "{}_{}_{}".format(base_id, int(time.time()), random.randint(1000, 9999))

        # 参数校验
        pos = args.get("pos")
        if not pos:
            print "错误：缺少pos参数"
            return
        dimensionId = args.get("dimensionId")
        if dimensionId is None:
            print "错误：缺少dimensionId参数"
            return
        dispersed_value = args.get("dispersed_value")
        if dispersed_value is None:
            print "错误：缺少dispersed_value参数"
            return
        levelId = args.get("levelId", 0)

        # 处理方块标识符
        block_name = args.get("block_name", "fangyu:smoke")
        if not block_name:
            block_name = "fangyu:smoke"
            print "警告：block_name为空，使用默认值 fangyu:smoke"

        # 处理生成延迟参数
        interval_delay = args.get("interval_delay")
        if interval_delay is None:
            interval_delay = args.get("delay", 3.0)
        try:
            interval_delay = float(interval_delay)
        except (TypeError, ValueError):
            interval_delay = 3.0
            print "警告：interval_delay参数无效，使用默认3.0秒"

        initial_delay = args.get("initial_delay")
        if initial_delay is None:
            if args.get("delay") is not None and args.get("interval_delay") is None:
                initial_delay = interval_delay
            else:
                initial_delay = 0.0
        try:
            initial_delay = float(initial_delay)
        except (TypeError, ValueError):
            initial_delay = 0.0
            print "警告：initial_delay参数无效，使用默认0.0秒"

        # 处理清除参数
        clear_enabled = args.get("clear_enabled", False)
        clear_delay = args.get("clear_delay", 0.0)
        try:
            clear_delay = float(clear_delay)
        except (TypeError, ValueError):
            clear_delay = 0.0
            print "警告：clear_delay参数无效，使用默认0.0秒"

        clear_interval = args.get("clear_interval")
        if clear_interval is None:
            clear_interval = interval_delay  # 默认与生成圈间间隔相同
        try:
            clear_interval = float(clear_interval)
        except (TypeError, ValueError):
            clear_interval = interval_delay
            print "警告：clear_interval参数无效，使用与生成间隔相同的值"

        # 计算坐标范围和分组
        pos_int = tuple(int(x) for x in pos)
        x0, y0, z0 = pos_int
        r = int(dispersed_value)
        r_sq = dispersed_value ** 2

        # 1. 收集球体内所有整数点，并按到球心的距离平方分组
        layers = {}  # key: 距离平方, value: 该距离的所有点列表
        for i in range(x0 - r, x0 + r + 1):
            for j in range(y0 - r, y0 + r + 1):
                for k in range(z0 - r, z0 + r + 1):
                    dx = i - x0
                    dy = j - y0
                    dz = k - z0
                    dist_sq = dx * dx + dy * dy + dz * dz
                    if dist_sq <= r_sq:
                        layers.setdefault(dist_sq, []).append((i, j, k))

        sorted_distances = sorted(layers.keys())
        if not sorted_distances:
            print "无任何方块需要生成"
            return

        # 2. 存储当前任务的状态到字典中
        self._smoke_tasks[task_id] = {
            'layers': layers,
            'sorted_distances': sorted_distances,
            'current_index': 0,
            'id': args.get("id"),
            'dimensionId': dimensionId,
            'levelId': levelId,
            'interval_delay': interval_delay,
            'block_name': block_name,
            'finished': False,
            'task_id': task_id,
            # 清除相关
            'clear_enabled': clear_enabled,
            'clear_delay': clear_delay,
            'clear_interval': clear_interval,
            'clearing': False,          # 标记是否正在清除，避免重复启动清除
        }

        # 3. 定义生成一圈的函数
        def generate_layer(*unused_args, **unused_kwargs):
            task = self._smoke_tasks.get(task_id)
            if not task or task['finished']:
                return

            # 获取当前圈的距离及对应的点列表
            dist_sq = task['sorted_distances'][task['current_index']]
            points = task['layers'][dist_sq]

            # 获取方块操作组件
            comp = serverApi.GetEngineCompFactory().CreateBlockInfo(task['id'])

            # 遍历当前圈的所有点，检测并替换方块
            for point in points:
                block_dict = comp.GetBlockNew(point, task['dimensionId'])
                block_name = block_dict.get('name') if block_dict else None
                if block_name in FangyuData.SmokeReplaceBlockList:
                    print (args.get("smoke_aux"))
                    block_dict = {
                        'name': task['block_name'],
                        'aux': args.get("smoke_aux")
                        }
                    comp.SetBlockNew(point, block_dict, 0, task['dimensionId'], False)

            # 移到下一圈
            task['current_index'] += 1

            # 若还有下一圈，则 interval_delay 秒后继续；否则完成并启动清除（如果需要）
            if task['current_index'] < len(task['sorted_distances']):
                timer_comp = serverApi.GetEngineCompFactory().CreateGame(task['levelId'])
                timer_comp.AddTimer(task['interval_delay'], generate_layer, (), {})
            else:
                task['finished'] = True

                # 如果启用了清除且尚未开始清除，则启动清除流程
                if task['clear_enabled'] and not task.get('clearing', False):
                    task['clearing'] = True
                    # 延迟 clear_delay 秒后开始清除
                    timer_comp = serverApi.GetEngineCompFactory().CreateGame(task['levelId'])
                    timer_comp.AddTimer(task['clear_delay'], start_clear, (), {})

        # 4. 定义清除流程
        def start_clear(*unused_args, **unused_kwargs):
            task = self._smoke_tasks.get(task_id)
            if not task or task.get('clearing_finished', False):
                return

            # 准备清除任务状态（复用生成时的 layers 和 sorted_distances，但按从大到小顺序）
            # 清除时从外到内，所以 sorted_distances 逆序
            clear_distances = list(reversed(task['sorted_distances']))
            task['clear_distances'] = clear_distances
            task['clear_index'] = 0
            task['clearing_finished'] = False

            def clear_layer(*unused_args2, **unused_kwargs2):
                task_clear = self._smoke_tasks.get(task_id)
                if not task_clear or task_clear.get('clearing_finished', False):
                    return

                # 获取当前要清除的层
                dist_sq = task_clear['clear_distances'][task_clear['clear_index']]
                points = task_clear['layers'][dist_sq]

                comp = serverApi.GetEngineCompFactory().CreateBlockInfo(task_clear['id'])

                # 只清除原本填充的方块
                for point in points:
                    block_dict = comp.GetBlockNew(point, task_clear['dimensionId'])
                    block_name = block_dict.get('name') if block_dict else None
                    if block_name == task_clear['block_name'] and block_dict.get('aux') == args.get("smoke_aux"):#确保只清除当前烟雾弹生成的方块
                        # 替换为空气
                        block_dict = {'name': 'minecraft:air'}
                        comp.SetBlockNew(point, block_dict, 0, task_clear['dimensionId'], False)

                task_clear['clear_index'] += 1

                if task_clear['clear_index'] < len(task_clear['clear_distances']):
                    # 继续下一层
                    timer_comp = serverApi.GetEngineCompFactory().CreateGame(task_clear['levelId'])
                    timer_comp.AddTimer(task_clear['clear_interval'], clear_layer, (), {})
                else:
                    # 清除完成
                    task_clear['clearing_finished'] = True
                    print "clear ok"
                    # 可选：完全删除任务
                    if task_id in self._smoke_tasks:
                        del self._smoke_tasks[task_id]

            # 启动第一层清除
            timer_comp = serverApi.GetEngineCompFactory().CreateGame(task['levelId'])
            timer_comp.AddTimer(0.0, clear_layer, (), {})  # 立即开始第一层

        # 5. 启动生成定时器（使用 initial_delay）
        timer_comp = serverApi.GetEngineCompFactory().CreateGame(levelId)
        timer_comp.AddTimer(initial_delay, generate_layer, (), {})


# 全局便捷函数（使用默认实例）
_default_generator = None


def comp_smoke(args):
    """
    全局便捷函数，使用默认的 SmokeGenerator 实例生成烟雾。
    """
    global _default_generator
    if _default_generator is None:
        _default_generator = SmokeGenerator()
    _default_generator.comp_smoke(args)


# 可选：直接暴露类，以便用户自行管理实例
__all__ = ['SmokeGenerator', 'comp_smoke']