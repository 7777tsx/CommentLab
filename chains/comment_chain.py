from __future__ import annotations

from models.schemas import (
    Comment,
    CommentAction,
    CommentBatch,
    ContentAnalysis,
    PersonaSpec,
    PublisherProfile,
)
from services.llm_client import ModelGateway


class CommentChain:
    def __init__(self, gateway: ModelGateway):
        self.gateway = gateway

    def run_round(
        self,
        *,
        post_text: str,
        profile: PublisherProfile,
        personas: list[PersonaSpec],
        visible_comments: list[Comment],
        round_no: int,
        version: str,
        analysis: ContentAnalysis | None = None,
    ) -> CommentBatch:
        payload = {
            "post_text": post_text,
            "publisher_profile": profile.model_dump(),
            "round_no": round_no,
            "version": version,
            "personas": [
                {
                    "persona_id": persona.persona_id,
                    "label": persona.label,
                    "description": persona.description,
                    "reading_depth": persona.reading_depth,
                    "trust": persona.trust,
                    "emotion_sensitivity": persona.emotion_sensitivity,
                    "controversy_tendency": persona.controversy_tendency,
                }
                for persona in personas
            ],
            "visible_comments": [
                {
                    "comment_id": comment.comment_id,
                    "persona_label": comment.persona_label,
                    "text": comment.text,
                    "likes": comment.likes,
                    "stance": comment.stance,
                }
                for comment in visible_comments[:4]
            ],
            "post_semantics": (
                {
                    "main_message": analysis.main_message,
                    "content_type": analysis.content_type,
                    "tone": analysis.tone,
                    "explicit_information": analysis.explicit_information[:3],
                    "reasonable_disagreements": analysis.reasonable_disagreements[:3],
                    "unsupported_inferences": analysis.unsupported_inferences[:3],
                    "possible_misreadings": analysis.possible_misreadings[:3],
                }
                if analysis else {}
            ),
        }
        candidate = self.gateway.invoke_structured(
            stage=f"comment_round_{version}_{round_no}",
            schema=CommentBatch,
            payload=payload,
            system_prompt=(
                "你是批量评论生成Agent。分别按每个Persona的阅读深度、信任、情绪和争议倾向行动。"
                "第一轮只能comment或ignore，后续轮可comment、reply、like或ignore。"
                "每条评论10到60个汉字，不模仿具体平台，不使用真实用户名，不做事实核查。"
                "回复只能指向提供的comment_id。不同Persona的理解和语气必须可区分。"
                "不要让所有人都要求补充信息；应包含情绪反应、个人联想、支持、质疑、调侃和不参与。"
                "后续轮仍要有新的顶级评论，回复分散到不同讨论分支，不要全部围绕同一条热评。"
                "每个动作先从post_semantics选择真正关注的内容，evidence_span填帖子或父评论中的实际短语，"
                "reaction_type填支持、个人联想、第一印象、质疑、调侃等反应类型。"
                "如果推断属于unsupported_inferences，只有高怀疑或争议Persona可能如此误读，不得当成事实。"
            ),
            fallback=lambda: self._demo_batch(
                post_text, personas, visible_comments, round_no, version, analysis
            ),
        )
        return self._diversify_actions(candidate, visible_comments, round_no)

    @staticmethod
    def _diversify_actions(
        batch: CommentBatch, visible_comments: list[Comment], round_no: int
    ) -> CommentBatch:
        """Keep later rounds from collapsing into a single reply thread."""
        if round_no == 1 or not visible_comments:
            return batch
        actions = [action.model_copy(deep=True) for action in batch.actions]
        conversational = [
            action for action in actions if action.action in {"comment", "reply"}
        ]
        if not conversational:
            return batch
        # Every later round contributes at least one fresh interpretation.
        conversational[0].action = "comment"
        conversational[0].target_comment_id = None
        # Replies join different visible branches instead of one dominant thread.
        targets = [comment.comment_id for comment in visible_comments]
        for index, action in enumerate(conversational[1:]):
            action.action = "reply"
            action.target_comment_id = targets[index % len(targets)]
        return CommentBatch(actions=actions)

    @staticmethod
    def _fit(text: str) -> str:
        if len(text) < 10:
            text += "我想知道更具体的情况。"
        return text[:60]

    def _demo_batch(
        self,
        post_text: str,
        personas: list[PersonaSpec],
        visible_comments: list[Comment],
        round_no: int,
        version: str,
        analysis: ContentAnalysis | None = None,
    ) -> CommentBatch:
        actions: list[CommentAction] = []
        for index, persona in enumerate(personas):
            text, stance, emotion, intensity, controversy, misunderstanding, off_topic = (
                self._semantic_demo_response(
                    persona.persona_id, post_text, version, round_no, index, analysis
                )
            )
            if round_no == 1 or not visible_comments or index == 0:
                action = "comment"
                target = None
            else:
                action = "reply"
                target = visible_comments[(index - 1) % len(visible_comments)].comment_id
            actions.append(
                CommentAction(
                    persona_id=persona.persona_id,
                    action=action,
                    target_comment_id=target,
                    text=self._fit(text),
                    stance=stance,
                    emotion=emotion,
                    emotion_intensity=intensity,
                    controversy=controversy,
                    misunderstanding=misunderstanding,
                    off_topic=off_topic,
                    evidence_span=(analysis.main_message if analysis else post_text)[:30],
                    reaction_type=self._reaction_type(persona.persona_id),
                )
            )
        return CommentBatch(actions=actions)

    @staticmethod
    def _reaction_type(persona_id: str) -> str:
        return {
            "core_fan": "support",
            "regular_follower": "personal_reaction",
            "passerby": "first_impression",
            "headline_reader": "simplification",
            "rational_questioner": "question",
            "expert_corrector": "qualification",
            "motive_skeptic": "motive_inference",
            "commercial_skeptic": "interest_check",
            "emotional_resonator": "personal_association",
            "meme_user": "humor",
            "controversy_amplifier": "polarization",
        }.get(persona_id, "opinion")

    @classmethod
    def _semantic_demo_response(
        cls,
        persona_id: str,
        post: str,
        version: str,
        round_no: int,
        index: int,
        analysis: ContentAnalysis | None,
    ) -> tuple[str, str, str, float, float, bool, bool]:
        focus = (analysis.main_message if analysis else post).strip("。！？\n ")
        focus = focus[:14] + ("…" if len(focus) > 14 else "")
        content_type = analysis.content_type if analysis else "其他"
        disagreement = (
            analysis.reasonable_disagreements[0]
            if analysis and analysis.reasonable_disagreements
            else "每个人的经验不一样"
        )
        responses = {
            "core_fan": (f"看到你说“{focus}”，我大概能理解你是怎么想的。", "support", "亲切", .28, .12, False, False),
            "regular_follower": (f"这条读完我的第一反应是：{focus}，挺有画面感的。", "neutral", "好奇", .35, .18, False, False),
            "passerby": (f"第一次刷到，我会把这理解成一种{content_type}，不一定是在说别人。", "neutral", "平静", .30, .20, False, False),
            "headline_reader": (f"我只记住了“{focus}”，直觉上这就是这条的重点。", "neutral", "直观", .42, .40, len(post) > 80, False),
            "rational_questioner": (f"结论我能跟上，但我更好奇你是怎么从具体经历得出“{focus}”的。", "question", "好奇", .32, .20, False, False),
            "expert_corrector": (f"“{focus}”作为个人感受没问题，但换个环境可能就不一样了。", "question", "审慎", .30, .28, False, False),
            "motive_skeptic": (f"怎么突然提到“{focus}”？我有点好奇是不是刚发生了什么。", "question", "怀疑", .55, .55, True, False),
            "commercial_skeptic": (f"单看这条还看不出有什么利益关系，先当普通的{content_type}看吧。", "neutral", "观望", .28, .22, False, False),
            "emotional_resonator": (f"“{focus}”这句让我想到自己也有过类似的时候，还挺共鸣的。", "support", "共鸣", .52, .18, False, False),
            "meme_user": (f"“{focus}”很有标题感，已经能想到评论区会怎么接话了。", "neutral", "调侃", .52, .65, False, True),
            "controversy_amplifier": (f"说白了，这条的重点就是“{focus}”，别把简单的话说得太绕。", "oppose", "强硬", .70, .82, True, True),
        }
        text, stance, emotion, intensity, controversy, misunderstanding, off_topic = responses.get(
            persona_id, list(responses.values())[index % len(responses)]
        )
        if round_no == 2:
            openings = ("看了前面的讨论，", "换个角度看，", "这点我部分同意，不过", "我倒觉得，")
            text = f"{openings[index % len(openings)]}{disagreement}。"
        elif round_no == 3:
            openings = ("讨论到这里，", "翻了一圈回复，", "说到最后，")
            text = f"{openings[index % len(openings)]}我还是更在意“{focus}”本身。"
        if version == "after":
            stance = "neutral" if stance == "oppose" else stance
            intensity = max(.15, intensity - .12)
            controversy = max(.10, controversy - .12)
            misunderstanding = False
        return text, stance, emotion, intensity, controversy, misunderstanding, off_topic

    @staticmethod
    def _demo_response(
        persona_id: str, post: str, version: str, round_no: int, index: int
    ) -> tuple[str, str, str, float, float, bool, bool]:
        after = version == "after"
        if ("减少" in post and "更新" in post) or "降低更新" in post:
            before_map = {
                "core_fan": ("最近是不是太累了？先照顾好自己，也等你说说具体安排。", "support", "关心", .35, .15, False, False),
                "regular_follower": ("适当减少到底是多久更新一次？希望能给一个大概范围。", "question", "疑惑", .45, .25, False, False),
                "passerby": ("只看这条像是在为停更做铺垫，后面还会继续更新吗？", "question", "怀疑", .65, .60, True, False),
                "headline_reader": ("所以这是准备慢慢停更了吗？不用多想反而让人更想多。", "oppose", "焦虑", .75, .75, True, False),
                "rational_questioner": ("希望补充调整频率、持续时间和原因，大家才有稳定预期。", "question", "平静", .25, .20, False, False),
                "expert_corrector": ("适当这个范围无法验证，建议把短期安排和恢复条件说清楚。", "question", "审慎", .30, .30, False, False),
                "motive_skeptic": ("是不是账号数据有变化才减少更新？这句话感觉省略了真正原因。", "oppose", "不信任", .80, .85, True, False),
                "commercial_skeptic": ("后面不会是把正常更新改成付费内容吧？最好提前说明。", "question", "警惕", .70, .70, True, True),
                "emotional_resonator": ("突然这样说有点失落，也担心以后是不是很难再等到更新。", "oppose", "失望", .75, .45, True, False),
                "meme_user": ("适当减少加不用多想，这听起来很像退网倒计时预告。", "neutral", "调侃", .65, .80, True, True),
                "controversy_amplifier": ("简单翻译一下：更新越来越少，但暂时不想直接说停更。", "oppose", "嘲讽", .85, .95, True, True),
            }
            after_map = {
                "core_fan": ("说明得挺清楚，先按自己的节奏来，后续安排再告诉大家。", "support", "理解", .20, .10, False, False),
                "regular_follower": ("知道是暂时调整就放心些，等后续公布更具体的安排。", "support", "平静", .20, .10, False, False),
                "passerby": ("至少明确是暂时减少，并承诺会更新安排，信息比之前完整。", "neutral", "平静", .20, .15, False, False),
                "headline_reader": ("看起来只是暂时少更一些，不是直接宣布停止更新。", "neutral", "平静", .25, .15, False, False),
                "rational_questioner": ("目前还缺具体频率，但已经说明后续会及时公布，可以理解。", "question", "平静", .20, .15, False, False),
                "expert_corrector": ("暂时和后续通知限定了范围，仍可再补一个预计时间点。", "question", "审慎", .20, .20, False, False),
                "motive_skeptic": ("原因还是没有展开，不过这次没有回避大家对安排的疑问。", "question", "怀疑", .35, .35, False, False),
                "commercial_skeptic": ("没有涉及付费或合作变化，目前不需要往商业化方向猜。", "neutral", "平静", .20, .15, False, False),
                "emotional_resonator": ("看到会及时说明安排，情绪上没那么突然了，也愿意等等。", "support", "理解", .25, .10, False, False),
                "meme_user": ("这次不是退网倒计时，比较像正常的短期节奏调整说明。", "neutral", "轻松", .30, .25, False, False),
                "controversy_amplifier": ("能看出是暂时调整，暂时没有足够信息说成彻底停更。", "neutral", "平静", .25, .25, False, False),
            }
            return (after_map if after else before_map).get(persona_id, list((after_map if after else before_map).values())[index % 3])

        if "有些人" in post or "指手画脚" in post:
            base = {
                "core_fan": ("应该是遇到越界评论了吧，支持表达边界，但最好说清具体行为。", "support", "关心", .45, .35, False, False),
                "regular_follower": ("这里的有些人具体指谁？范围不清楚会让很多人觉得在说自己。", "question", "疑惑", .55, .55, True, False),
                "passerby": ("不了解前因后果，只看文字会觉得是在拒绝所有不同意见。", "oppose", "不适", .65, .65, True, False),
                "headline_reader": ("所以只要意见不一样就算指手画脚吗？这个态度有点强硬。", "oppose", "愤怒", .75, .80, True, False),
                "rational_questioner": ("建议区分越界行为和正常意见，否则讨论对象会变成人而不是事情。", "question", "平静", .30, .30, False, False),
                "expert_corrector": ("尊重是原则，但有些人和什么事情都过于概括，边界需要定义。", "question", "审慎", .30, .40, False, False),
                "motive_skeptic": ("不点名又公开发出来，是不是想让粉丝自行猜人并围攻？", "oppose", "不信任", .80, .90, True, True),
                "commercial_skeptic": ("如果这是回应合作或推广质疑，最好把利益关系也说明白。", "question", "警惕", .55, .55, True, True),
                "emotional_resonator": ("这种语气会让认真提建议的人也觉得不被尊重，很容易受伤。", "oppose", "失望", .75, .55, True, False),
                "meme_user": ("翻译一下：可以评论，但不许指点；评论区边界测试开始了。", "neutral", "调侃", .70, .85, True, True),
                "controversy_amplifier": ("一句话概括就是创作者不接受批评，支持者别再替他找补了。", "oppose", "嘲讽", .90, .95, True, True),
            }
            if after:
                return ("现在明确针对越界行为而不是某类人，讨论边界清楚了不少。", "neutral", "平静", .25, .20, False, False)
            return base.get(persona_id, list(base.values())[index % 3])

        if "处理得不够好" in post or "不要只看结果" in post:
            base = {
                "core_fan": ("愿意承认问题是第一步，也希望后续能把补救措施说清楚。", "support", "期待", .35, .20, False, False),
                "regular_follower": ("承认之后马上说情况复杂，读起来还是有一点像在解释自己。", "question", "疑惑", .50, .45, True, False),
                "passerby": ("结果已经造成影响，让大家不要只看结果会显得没有面对重点。", "oppose", "失望", .70, .65, True, False),
                "headline_reader": ("前面道歉后面转折，这不就是先说对不起再说自己也没办法吗？", "oppose", "愤怒", .80, .85, True, False),
                "rational_questioner": ("复杂情况可以补充，但应先说明具体责任、影响和补救计划。", "question", "平静", .30, .25, False, False),
                "expert_corrector": ("但字让责任表达和背景说明形成对立，建议拆成两个层次。", "question", "审慎", .30, .35, False, False),
                "motive_skeptic": ("所谓复杂情况是不是在为自己的决定找理由？现在仍没说怎么补救。", "oppose", "不信任", .80, .85, True, False),
                "commercial_skeptic": ("如果涉及合作或利益影响，至少应该说明责任和处理方式。", "question", "警惕", .55, .50, False, False),
                "emotional_resonator": ("受到影响的人最在意结果，这样说会让人感觉自己的感受被否定。", "oppose", "被忽视", .85, .60, True, False),
                "meme_user": ("经典句式出现了：我有问题，但是情况复杂，请大家理解过程。", "neutral", "调侃", .70, .85, True, True),
                "controversy_amplifier": ("这不是道歉而是辩解，重点全在要求别人理解自己。", "oppose", "嘲讽", .90, .95, True, False),
            }
            if after:
                after_map = {
                    "core_fan": ("先承认结果再说明背景，能看出没有回避责任，也愿意等后续说明。", "support", "理解", .20, .10, False, False),
                    "regular_follower": ("这次责任和背景分开说了，至少不会觉得一句但是把道歉抵消。", "neutral", "平静", .20, .15, False, False),
                    "passerby": ("不了解前情也能看到先承担结果，态度比原文更直接和清楚。", "neutral", "平静", .20, .15, False, False),
                    "headline_reader": ("核心信息是承认处理有问题，不再像先道歉后找理由。", "neutral", "平静", .25, .15, False, False),
                    "rational_questioner": ("责任表达清楚了，后续仍希望看到具体补救和背景说明。", "question", "审慎", .25, .20, False, False),
                    "expert_corrector": ("把责任和解释拆开后逻辑层次更清楚，转折不再削弱前句。", "support", "认可", .20, .15, False, False),
                    "motive_skeptic": ("暂时还没看到补救细节，但这版至少没有要求受众忽略结果。", "question", "怀疑", .35, .30, False, False),
                    "commercial_skeptic": ("如果涉及合作利益，后续还应说明处理方式，但当前责任表述合理。", "question", "警惕", .30, .25, False, False),
                    "emotional_resonator": ("先接住大家对结果的失望，再解释背景，会让受影响的人更被尊重。", "support", "被理解", .25, .15, False, False),
                    "meme_user": ("这版不太像经典转折道歉，想截成辩解梗也没有那么顺手了。", "neutral", "轻松", .30, .25, False, False),
                    "controversy_amplifier": ("文本已经先明确承担责任，直接说成完全没道歉会缺少依据。", "neutral", "平静", .25, .30, False, False),
                }
                return after_map.get(persona_id, list(after_map.values())[index % 3])
            return base.get(persona_id, list(base.values())[index % 3])

        # Open-domain fallback: react to what was actually written instead of making
        # every persona ask for "more complete information".
        topic = post.strip("。！？\n ")
        if len(topic) > 18:
            topic = topic[:18] + "…"
        soft = .12 if after else 0
        generic = {
            "core_fan": (f"看到“{topic}”了，感觉这还是你一贯的表达，我能理解。", "support", "亲切", .28, .12, False, False),
            "regular_follower": (f"这条读完的第一反应是“{topic}”，有点意外，但也不难接受。", "neutral", "意外", .38, .18, False, False),
            "passerby": (f"第一次刷到，我会把“{topic}”理解成作者当下的真实态度。", "neutral", "好奇", .34, .22, False, False),
            "headline_reader": (f"我只记住了“{topic}”，听起来态度挺明确的。", "neutral", "直观", .42, .36, len(post) > 80, False),
            "rational_questioner": (f"这个结论我能跟上，不过我更想知道你是怎么走到“{topic}”的。", "question", "好奇", .32, .20, False, False),
            "expert_corrector": (f"“{topic}”里结论比较强，但这更像个人判断，不必当成普遍结论。", "question", "审慎", .30, .28, False, False),
            "motive_skeptic": (f"怎么突然发“{topic}”？感觉前面应该发生了点什么。", "question", "怀疑", .58, .58, True, False),
            "commercial_skeptic": (f"先看后续吧，单看“{topic}”还没必要往合作或利益上猜。", "neutral", "观望", .30, .25, False, False),
            "emotional_resonator": (f"不知道为什么，“{topic}”这句让我有点共鸣，会想到自己的经历。", "support", "共鸣", .52, .20, False, False),
            "meme_user": (f"“{topic}”这句很有标题感，我已经能想到评论区会怎么接了。", "neutral", "调侃", .55, .68, False, True),
            "controversy_amplifier": (f"说白了，这条的重点就是“{topic}”，其他解释都是次要的。", "oppose", "强硬", .72, .82, True, True),
        }
        response = generic.get(persona_id, list(generic.values())[index % len(generic)])
        text, stance, emotion, intensity, controversy, misunderstanding, off_topic = response
        if round_no == 2:
            text = "看了前面的讨论，" + text.replace(f"“{topic}”", "这个说法", 1)
        elif round_no == 3:
            text = "讨论到这里，我还是觉得：" + text.replace(
                f"“{topic}”", "这句话", 1
            )
        if not after:
            return text, stance, emotion, intensity, controversy, misunderstanding, off_topic
        return (
            text,
            "neutral" if stance == "oppose" else stance,
            emotion,
            max(.15, intensity - soft),
            max(.10, controversy - soft),
            False,
            off_topic,
        )
