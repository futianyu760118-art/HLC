"""
面试结果AI分析服务
支持文本解析，预留音频/视频接口
"""
import json
import os
from datetime import datetime

SILICONFLOW_API_KEY = os.getenv('SILICONFLOW_API_KEY', '')
SILICONFLOW_API_URL = os.getenv('SILICONFLOW_API_URL', 'https://api.siliconflow.cn/v1')
SILICONFLOW_MODEL = os.getenv('SILICONFLOW_MODEL', 'deepseek-ai/DeepSeek-V3')


def analyze_interview_text(
    feedback_text: str,
    candidate_name: str,
    job_title: str,
    job_description: str,
    resume_summary: str = None
) -> dict:
    """
    分析面试反馈文本，生成AI评估报告
    
    Args:
        feedback_text: 面试反馈/记录文本
        candidate_name: 候选人姓名
        job_title: 岗位名称
        job_description: 岗位描述
        resume_summary: 简历摘要（可选）
    
    Returns:
        AI分析结果字典
    """
    try:
        resume_context = f"\n【候选人简历摘要】\n{resume_summary}" if resume_summary else ""
        
        prompt = f"""你是一位资深的HR面试官和人才评估专家，拥有丰富的面试评估经验。请根据以下面试反馈内容，对候选人进行全面、专业的评估分析。

【候选人信息】
姓名：{candidate_name}
应聘岗位：{job_title}
岗位要求：{job_description}
{resume_context}

【面试反馈内容】
{feedback_text[:5000]}

【评估维度说明】
请从以下维度进行评估，每个维度0-100分：
1. 专业能力 (professionalScore): 专业知识深度、技术能力、问题解决能力
2. 沟通表达 (communicationScore): 语言表达清晰度、逻辑性、倾听理解能力
3. 团队协作 (teamworkScore): 团队合作意识、协调能力、冲突处理
4. 学习能力 (learningScore): 学习意愿、适应能力、成长潜力
5. 文化匹配 (cultureScore): 价值观契合度、工作态度、职业素养

【输出要求】
请严格按照以下JSON格式返回分析结果，不要添加任何其他文字说明：

{{
  "overallScore": 综合评分(0-100的整数),
  "overallLevel": "优秀/良好/一般/待提升/不合格",
  "recommendation": "强烈推荐录用/推荐录用/建议复试/暂不推荐/不推荐",
  "dimensions": {{
    "professionalScore": 专业能力分数,
    "communicationScore": 沟通表达分数,
    "teamworkScore": 团队协作分数,
    "learningScore": 学习能力分数,
    "cultureScore": 文化匹配分数
  }},
  "summary": "综合评价（3-5句话，概括候选人的整体表现、核心优势和主要不足）",
  "strengths": ["优势1", "优势2", "优势3"],
  "weaknesses": ["不足1", "不足2"],
  "keyObservations": [
    {{
      "aspect": "观察维度",
      "observation": "具体观察内容",
      "suggestion": "建议或关注点"
    }}
  ],
  "riskFactors": ["潜在风险或顾虑点"],
  "hiringAdvice": "录用建议（详细说明是否录用以及理由，包括薪资定级建议、试用期关注点等）",
  "followUpQuestions": ["后续需要确认的问题1", "问题2"],
  "onboardingTips": ["入职后需要关注的事项1", "事项2"]
}}

【评分标准】
- 90-100分：表现优秀，该维度明显高于岗位要求
- 80-89分：表现良好，完全满足岗位要求
- 70-79分：表现一般，基本满足岗位要求
- 60-69分：表现欠佳，部分满足岗位要求
- 60分以下：表现不足，不满足岗位要求

请确保评分客观、分析深入、建议具体可操作。
"""
        
        print(f'[面试分析] 开始分析 {candidate_name} 的面试反馈...')
        print('[面试分析] 使用受控模型策略')
        from services.assistant_core import llm_client

        ai_result = llm_client.json_chat_profile(
            'standard',
            [
                {
                    'role': 'system',
                    'content': '你是一位专业的HR面试评估专家，擅长从面试反馈中提取关键信息并给出专业评估。请严格按照JSON格式返回结果。'
                },
                {
                    'role': 'user',
                    'content': prompt
                }
            ],
            temperature=0.7,
            max_tokens=3000,
            timeout=60,
            use_case='interview_analysis',
            resource_domain='interview_ai',
        )
        if not ai_result:
            raise Exception('AI未返回有效JSON')
        print('[面试分析] JSON解析成功')
        
        # 验证和规范化结果
        result = normalize_analysis_result(ai_result)
        
        print(f'[面试分析] ✓ 分析完成 - 综合评分: {result["overallScore"]}')
        return result
        
    except Exception as e:
        print(f'[面试分析] 分析失败: {str(e)}')
        return generate_fallback_result(candidate_name)


def analyze_interview_audio(file_path: str, **kwargs) -> dict:
    """
    分析面试音频文件（预留接口）
    
    Args:
        file_path: 音频文件路径
        **kwargs: 其他参数（candidate_name, job_title等）
    
    Returns:
        AI分析结果字典
    """
    # 已知待办（非 bug）：集成语音转文字服务（阿里云 ASR / 讯飞）
    # 当前回退为文本分析模式，需文本输入。音频分析待接入。
    # 1. 调用 ASR 服务将音频转为文字
    # 2. 调用 analyze_interview_text 进行分析
    
    print(f'[面试分析] 音频分析功能开发中...')
    return {
        'error': '音频分析功能即将上线',
        'status': 'not_implemented',
        'message': '当前版本暂不支持音频分析，请使用文本方式提交面试反馈'
    }


def analyze_interview_video(file_path: str, **kwargs) -> dict:
    """
    分析面试视频文件（预留接口）
    
    Args:
        file_path: 视频文件路径
        **kwargs: 其他参数（candidate_name, job_title等）
    
    Returns:
        AI分析结果字典
    """
    # 已知待办（非 bug）：集成视频分析服务
    # 当前回退为文本分析模式。视频智能分析待接入。
    # 1. 提取视频音轨转文字
    # 2. （可选）分析面部表情、肢体语言等非语言信息
    # 3. 调用 analyze_interview_text 进行分析
    
    print(f'[面试分析] 视频分析功能开发中...')
    return {
        'error': '视频分析功能即将上线',
        'status': 'not_implemented',
        'message': '当前版本暂不支持视频分析，请使用文本方式提交面试反馈'
    }


def normalize_analysis_result(ai_result: dict) -> dict:
    """规范化AI返回的分析结果"""
    
    # 确保所有必需字段存在
    overall_score = int(ai_result.get('overallScore', 70))
    overall_score = max(0, min(100, overall_score))
    
    dimensions = ai_result.get('dimensions', {})
    normalized_dimensions = {
        'professionalScore': max(0, min(100, int(dimensions.get('professionalScore', 70)))),
        'communicationScore': max(0, min(100, int(dimensions.get('communicationScore', 70)))),
        'teamworkScore': max(0, min(100, int(dimensions.get('teamworkScore', 70)))),
        'learningScore': max(0, min(100, int(dimensions.get('learningScore', 70)))),
        'cultureScore': max(0, min(100, int(dimensions.get('cultureScore', 70))))
    }
    
    return {
        'overallScore': overall_score,
        'overallLevel': ai_result.get('overallLevel', get_level_by_score(overall_score)),
        'recommendation': ai_result.get('recommendation', '建议复试'),
        'dimensions': normalized_dimensions,
        'summary': ai_result.get('summary', '暂无综合评价'),
        'strengths': ai_result.get('strengths', [])[:5],
        'weaknesses': ai_result.get('weaknesses', [])[:3],
        'keyObservations': ai_result.get('keyObservations', [])[:5],
        'riskFactors': ai_result.get('riskFactors', [])[:3],
        'hiringAdvice': ai_result.get('hiringAdvice', '建议进行复试以做进一步评估'),
        'followUpQuestions': ai_result.get('followUpQuestions', [])[:3],
        'onboardingTips': ai_result.get('onboardingTips', [])[:3]
    }


def get_level_by_score(score: int) -> str:
    """根据分数返回等级"""
    if score >= 90:
        return '优秀'
    elif score >= 80:
        return '良好'
    elif score >= 70:
        return '一般'
    elif score >= 60:
        return '待提升'
    else:
        return '不合格'


def generate_fallback_result(candidate_name: str) -> dict:
    """生成备用结果（AI分析失败时使用）"""
    return {
        'overallScore': 70,
        'overallLevel': '一般',
        'recommendation': '建议复试',
        'dimensions': {
            'professionalScore': 70,
            'communicationScore': 70,
            'teamworkScore': 70,
            'learningScore': 70,
            'cultureScore': 70
        },
        'summary': f'已收到{candidate_name}的面试反馈，由于系统原因暂时无法生成详细分析，建议人工评估。',
        'strengths': ['待人工评估'],
        'weaknesses': ['待人工评估'],
        'keyObservations': [],
        'riskFactors': [],
        'hiringAdvice': '建议由面试官进行人工评估后做出决定',
        'followUpQuestions': [],
        'onboardingTips': []
    }
