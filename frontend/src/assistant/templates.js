export const templates = [
    { id: 'chat', icon: 'chat', title: '通用对话', hint: '问题解答、写作与头脑风暴', prompt: '' },
    { id: 'summary', icon: 'video', title: '视频总结', hint: '快速了解核心内容和重点', prompt: '请总结视频的主要内容，整理关键观点，并给出时间点依据。', video: true },
    { id: 'notes', icon: 'book', title: '学习笔记', hint: '概念、案例与复习清单', prompt: '请将课程视频整理成结构化学习笔记，提取核心概念、案例和复习问题。', video: true },
    { id: 'meeting', icon: 'users', title: '会议纪要', hint: '议题、决策和待办事项', prompt: '请整理会议议题、决策和行动项，未提及的负责人或截止日期请明确标注。', video: true },
    { id: 'timeline', icon: 'clock', title: '章节时间轴', hint: '按时间线查看视频要点', prompt: '请根据视频整理章节时间轴，使用原文中的时间点。', video: true },
    { id: 'mindmap', icon: 'tree', title: '思维导图', hint: '将知识转为可折叠的结构树', prompt: '请从视频中提取知识框架，生成分层思维导图。', video: true },
    { id: 'script', icon: 'file', title: '短视频脚本', hint: '开场、内容结构与结尾', prompt: '请帮我写一份短视频脚本，包含标题、开场、主体和结尾。' },
    { id: 'compare', icon: 'folder', title: '多视频对比', hint: '对比共识、差异与证据', prompt: '请对比这些视频的共同观点、差异和不确定性，分别引用各视频依据。', video: true },
    { id: 'research', icon: 'globe', title: '联网研究', hint: '结合搜索结果与视频证据', prompt: '请结合网页搜索和已添加的视频，分析我的问题，并标注来源。', capability: 'web' },
    { id: 'visual', icon: 'video', title: '画面分析', hint: '抽样帧理解，不代表逐帧观看', prompt: '请分析视频抽样画面，结合文字稿给出发现，并说明抽样局限。', capability: 'visual', video: true },
    { id: 'agent', icon: 'sparkle', title: '工具协同', hint: '有边界的检索与分析步骤', prompt: '请使用可用的只读工具完成分析，给出依据和局限。' },
    { id: 'study_pack', icon: 'folder', title: '学习资料包', hint: '依次生成笔记、时间轴和导图', prompt: '请生成完整的学习资料包：笔记、时间轴和思维导图。', video: true },
];
export const getTemplate = id => templates.find(t => t.id === id) || templates[0];
