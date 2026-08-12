/**
 * Traditional Chinese (Hong Kong). Keys mirror the English source locale
 * exactly (see locales/en.ts); missing keys fall back to English.
 */
export default {
  // App shell / navigation
  Overview: "總覽",
  Inspections: "檢驗記錄",
  Reviews: "人工覆核",
  "Sign out": "登出",
  "Primary navigation": "主導航",
  "Interface language": "介面語言",

  // Shared status words
  OK: "OK",
  NG: "NG",
  Uncertain: "不確定",
  Result: "結果",
  "Internal decision": "內部判定",
  Internal: "內部判定",
  Lifecycle: "生命週期",
  Product: "產品",
  Barcode: "條碼",
  Device: "設備",
  "Device id": "設備 ID",
  Site: "站點",
  Line: "產線",
  Name: "名稱",
  State: "狀態",
  Component: "元件",
  Detail: "詳情",
  Inspection: "檢驗",
  Review: "人工覆核",
  Rev: "版",
  Disposition: "處置意見",
  Reviewer: "覆核人",
  Reason: "原因",
  Reasons: "原因",
  Media: "媒體",

  // Common actions
  "Sign in": "登入",
  Apply: "套用",
  Clear: "清除",
  Cancel: "取消",
  Previous: "上一頁",
  "Next page": "下一頁",
  "Append review": "附加覆核",
  "Record review": "記錄覆核",
  "Review queue": "覆核佇列",

  // Login
  "Pilot administrator sign-in": "試點管理員登入",
  "Administrator token": "管理員令牌",
  "Authentication failed; check the pilot administrator token.":
    "認證失敗；請檢查試點管理員令牌。",

  // Overview
  "Counts are sample denominators for the selected scope, not accuracy claims.":
    "計數是所選範圍內的樣本分母，並非準確率聲明。",
  "From (UTC)": "從 (UTC)",
  "To (UTC)": "至 (UTC)",
  "Mean upload delay": "平均上傳延遲",
  "Daily outcomes": "每日判定",
  Devices: "設備",
  "No registered devices.": "沒有已註冊的設備。",
  "Last seen (UTC)": "最後上線 (UTC)",
  "failed to load the dashboard": "儀表板載入失敗",

  // Inspection history
  "Inspection history": "檢驗歷史記錄",
  "Cross-device records with bounded filters and keyset pagination.":
    "跨設備記錄，支援有界篩選與鍵集分頁。",
  "Reason code": "原因代碼",
  "Rule version id": "規則版本 ID",
  "Model version id": "模型版本 ID",
  "No inspections match the filters.": "沒有符合篩選條件的檢驗記錄。",
  "Completed (UTC)": "完成時間 (UTC)",
  "Upload delay": "上傳延遲",
  "failed to load inspections": "檢驗記錄載入失敗",

  // Inspection detail
  "Inspection {id}": "檢驗 {id}",
  "reviewed r{revision}: {disposition}": "已覆核 r{revision}：{disposition}",
  "Original edge evidence; reviewed labels are shown separately.":
    "原始邊緣證據；覆核標籤會單獨顯示。",
  Decision: "判定",
  "Missing components": "缺失元件",
  "Reason codes": "原因代碼",
  Receipt: "回執",
  "Receipt status": "回執狀態",
  "Accepted (UTC)": "受理時間 (UTC)",
  "Component evidence": "元件證據",
  "Best confidence": "最高置信度",
  Detections: "偵測數",
  "Usable frames": "有效幀數",
  "No component evidence recorded.": "未記錄元件證據。",
  "Versions and traceability": "版本與追溯",
  Application: "應用程式",
  "Rule version": "規則版本",
  "Product model": "產品模型",
  "Component model": "元件模型",
  "Aggregation policy": "聚合策略",
  Processing: "處理耗時",
  "Inference traceability": "推理追溯",
  "Product latency": "產品偵測延遲",
  "Component latency": "元件偵測延遲",
  "No review recorded yet.": "尚未記錄覆核。",
  "No review recorded.": "沒有覆核記錄。",
  "Recorded (UTC)": "記錄時間 (UTC)",
  "Appends revision {revision} with optimistic If-Match; the machine decision is never modified.":
    "將以樂觀 If-Match 附加修訂版 {revision}；機器判定不會被修改。",
  "Bounded reason (optional)": "受限原因（可選）",
  "No media bound to this inspection.": "該檢驗未綁定媒體。",
  "Enlarge media": "放大媒體",
  "Review recorded.": "覆核已記錄。",
  "A newer review exists; the page was refreshed.": "存在較新的覆核；頁面已重新整理。",
  "failed to load the inspection": "檢驗詳情載入失敗",
  "failed to submit the review": "覆核提交失敗",

  // Review queue
  "NG and uncertain inspections awaiting append-only review. Machine outcomes are never modified; reviewed labels are shown separately.":
    "等待附加式覆核的 NG 與不確定檢驗。機器判定不會被修改；覆核標籤會單獨顯示。",
  "No inspections awaiting review.": "沒有待覆核的檢驗。",
  "Machine result": "機器判定",
  "The original machine decision and evidence remain unchanged; this appends a reviewer disposition (revision 1 of an unreviewed inspection).":
    "原始機器判定與證據保持不變；此操作會附加覆核處置（未覆核檢驗的第 1 版）。",
  "Bounded review reason (optional)": "受限覆核原因（可選）",
  "Review r{revision} recorded ({disposition}).": "覆核 r{revision} 已記錄（{disposition}）。",
  "This inspection was reviewed by someone else; refresh the queue.":
    "該檢驗已被他人覆核；請重新整理佇列。",
  "failed to load the review queue": "覆核佇列載入失敗",

  // Review dispositions (design 24.3; labels align with edge-web)
  "Confirmed NG": "確認 NG",
  "Confirmed OK": "確認 OK",
  "Corrected NG": "更正為 NG",
  Inconclusive: "無法定論",
  Reinspect: "複檢",
};
