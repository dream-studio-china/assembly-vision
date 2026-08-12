/**
 * Simplified Chinese (Mainland China). Keys mirror the English source locale
 * exactly (see locales/en.ts); missing keys fall back to English.
 */
export default {
  // App shell / navigation
  Overview: "总览",
  Inspections: "检验记录",
  Reviews: "人工复核",
  "Sign out": "退出登录",
  "Primary navigation": "主导航",
  "Interface language": "界面语言",

  // Shared status words
  OK: "OK",
  NG: "NG",
  Uncertain: "不确定",
  Result: "结果",
  "Internal decision": "内部判定",
  Internal: "内部判定",
  Lifecycle: "生命周期",
  Product: "产品",
  Barcode: "条码",
  Device: "设备",
  "Device id": "设备 ID",
  Site: "站点",
  Line: "产线",
  Name: "名称",
  State: "状态",
  Component: "组件",
  Detail: "详情",
  Inspection: "检验",
  Review: "人工复核",
  Rev: "版",
  Disposition: "处置意见",
  Reviewer: "复核人",
  Reason: "原因",
  Reasons: "原因",
  Media: "媒体",

  // Common actions
  "Sign in": "登录",
  Apply: "应用",
  Clear: "清除",
  Cancel: "取消",
  Previous: "上一页",
  "Next page": "下一页",
  "Append review": "追加复核",
  "Record review": "记录复核",
  "Review queue": "复核队列",

  // Login
  "Pilot administrator sign-in": "试点管理员登录",
  "Administrator token": "管理员令牌",
  "Authentication failed; check the pilot administrator token.":
    "认证失败；请检查试点管理员令牌。",

  // Overview
  "Counts are sample denominators for the selected scope, not accuracy claims.":
    "计数是所选范围内的样本分母，并非准确率声明。",
  "From (UTC)": "从 (UTC)",
  "To (UTC)": "至 (UTC)",
  "Mean upload delay": "平均上传延迟",
  "Daily outcomes": "每日判定",
  Devices: "设备",
  "No registered devices.": "没有已注册的设备。",
  "Last seen (UTC)": "最后在线 (UTC)",
  "failed to load the dashboard": "仪表盘加载失败",

  // Inspection history
  "Inspection history": "检验历史记录",
  "Cross-device records with bounded filters and keyset pagination.":
    "跨设备记录，支持有界筛选与键集分页。",
  "Reason code": "原因代码",
  "Rule version id": "规则版本 ID",
  "Model version id": "模型版本 ID",
  "No inspections match the filters.": "没有符合筛选条件的检验记录。",
  "Completed (UTC)": "完成时间 (UTC)",
  "Upload delay": "上传延迟",
  "failed to load inspections": "检验记录加载失败",

  // Inspection detail
  "Inspection {id}": "检验 {id}",
  "reviewed r{revision}: {disposition}": "已复核 r{revision}：{disposition}",
  "Original edge evidence; reviewed labels are shown separately.":
    "原始边缘证据；复核标签单独显示。",
  Decision: "判定",
  "Missing components": "缺失组件",
  "Reason codes": "原因代码",
  Receipt: "回执",
  "Receipt status": "回执状态",
  "Accepted (UTC)": "受理时间 (UTC)",
  "Component evidence": "组件证据",
  "Best confidence": "最高置信度",
  Detections: "检测数",
  "Usable frames": "有效帧数",
  "No component evidence recorded.": "未记录组件证据。",
  "Versions and traceability": "版本与追溯",
  Application: "应用",
  "Rule version": "规则版本",
  "Product model": "产品模型",
  "Component model": "组件模型",
  "Aggregation policy": "聚合策略",
  Processing: "处理耗时",
  "Inference traceability": "推理追溯",
  "Product latency": "产品检测延迟",
  "Component latency": "组件检测延迟",
  "No review recorded yet.": "尚未记录复核。",
  "No review recorded.": "没有复核记录。",
  "Recorded (UTC)": "记录时间 (UTC)",
  "Appends revision {revision} with optimistic If-Match; the machine decision is never modified.":
    "将以乐观 If-Match 追加修订版 {revision}；机器判定不会被修改。",
  "Bounded reason (optional)": "受限原因（可选）",
  "No media bound to this inspection.": "该检验未绑定媒体。",
  "Enlarge media": "放大媒体",
  "Review recorded.": "复核已记录。",
  "A newer review exists; the page was refreshed.": "存在更新的复核；页面已刷新。",
  "failed to load the inspection": "检验详情加载失败",
  "failed to submit the review": "复核提交失败",

  // Review queue
  "NG and uncertain inspections awaiting append-only review. Machine outcomes are never modified; reviewed labels are shown separately.":
    "等待追加式复核的 NG 与不确定检验。机器判定不会被修改；复核标签单独显示。",
  "No inspections awaiting review.": "没有待复核的检验。",
  "Machine result": "机器判定",
  "The original machine decision and evidence remain unchanged; this appends a reviewer disposition (revision 1 of an unreviewed inspection).":
    "原始机器判定与证据保持不变；此操作会追加复核处置（未复核检验的第 1 版）。",
  "Bounded review reason (optional)": "受限复核原因（可选）",
  "Review r{revision} recorded ({disposition}).": "复核 r{revision} 已记录（{disposition}）。",
  "This inspection was reviewed by someone else; refresh the queue.":
    "该检验已被他人复核；请刷新队列。",
  "failed to load the review queue": "复核队列加载失败",

  // Review dispositions (design 24.3; labels align with edge-web)
  "Confirmed NG": "确认 NG",
  "Confirmed OK": "确认 OK",
  "Corrected NG": "纠正为 NG",
  Inconclusive: "无法定论",
  Reinspect: "复检",
};
