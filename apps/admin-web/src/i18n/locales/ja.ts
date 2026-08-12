/**
 * Japanese. Keys mirror the English source locale exactly (see locales/en.ts);
 * missing keys fall back to English.
 */
export default {
  // App shell / navigation
  Overview: "概要",
  Inspections: "検査記録",
  Reviews: "レビュー",
  "Sign out": "サインアウト",
  "Primary navigation": "メインナビゲーション",
  "Interface language": "表示言語",

  // Shared status words
  OK: "OK",
  NG: "NG",
  Uncertain: "不確実",
  Result: "結果",
  "Internal decision": "内部判定",
  Internal: "内部判定",
  Lifecycle: "ライフサイクル",
  Product: "製品",
  Barcode: "バーコード",
  Device: "デバイス",
  "Device id": "デバイス ID",
  Site: "サイト",
  Line: "ライン",
  Name: "名前",
  State: "状態",
  Component: "部品",
  Detail: "詳細",
  Inspection: "検査",
  Review: "レビュー",
  Rev: "版",
  Disposition: "処置",
  Reviewer: "レビューアー",
  Reason: "理由",
  Reasons: "理由",
  Media: "メディア",

  // Common actions
  "Sign in": "サインイン",
  Apply: "適用",
  Clear: "クリア",
  Cancel: "キャンセル",
  Previous: "前のページ",
  "Next page": "次のページ",
  "Append review": "レビューを追加",
  "Record review": "レビューを記録",
  "Review queue": "レビューキュー",

  // Login
  "Pilot administrator sign-in": "パイロット管理者サインイン",
  "Administrator token": "管理者トークン",
  "Authentication failed; check the pilot administrator token.":
    "認証に失敗しました。パイロット管理者トークンを確認してください。",

  // Overview
  "Counts are sample denominators for the selected scope, not accuracy claims.":
    "カウントは選択範囲のサンプル母数であり、精度を保証するものではありません。",
  "From (UTC)": "開始 (UTC)",
  "To (UTC)": "終了 (UTC)",
  "Mean upload delay": "平均アップロード遅延",
  "Daily outcomes": "日次判定",
  Devices: "デバイス",
  "No registered devices.": "登録済みデバイスはありません。",
  "Last seen (UTC)": "最終確認 (UTC)",
  "failed to load the dashboard": "ダッシュボードの読み込みに失敗しました",

  // Inspection history
  "Inspection history": "検査履歴",
  "Cross-device records with bounded filters and keyset pagination.":
    "複数デバイスの記録を、制限付きフィルターとキーセットページングで表示します。",
  "Reason code": "理由コード",
  "Rule version id": "ルールバージョン ID",
  "Model version id": "モデルバージョン ID",
  "No inspections match the filters.": "フィルターに一致する検査記録はありません。",
  "Completed (UTC)": "完了 (UTC)",
  "Upload delay": "アップロード遅延",
  "failed to load inspections": "検査記録の読み込みに失敗しました",

  // Inspection detail
  "Inspection {id}": "検査 {id}",
  "reviewed r{revision}: {disposition}": "レビュー済み r{revision}：{disposition}",
  "Original edge evidence; reviewed labels are shown separately.":
    "元のエッジ証拠です。レビューラベルは別途表示されます。",
  Decision: "判定",
  "Missing components": "欠落コンポーネント",
  "Reason codes": "理由コード",
  Receipt: "受領",
  "Receipt status": "受領ステータス",
  "Accepted (UTC)": "受理 (UTC)",
  "Component evidence": "コンポーネント証拠",
  "Best confidence": "最高信頼度",
  Detections: "検出数",
  "Usable frames": "有効フレーム数",
  "No component evidence recorded.": "コンポーネント証拠は記録されていません。",
  "Versions and traceability": "バージョンとトレーサビリティ",
  Application: "アプリケーション",
  "Rule version": "ルールバージョン",
  "Product model": "製品モデル",
  "Component model": "コンポーネントモデル",
  "Aggregation policy": "集約ポリシー",
  Processing: "処理時間",
  "Inference traceability": "推論トレーサビリティ",
  "Product latency": "製品検出レイテンシ",
  "Component latency": "コンポーネント検出レイテンシ",
  "No review recorded yet.": "まだレビューは記録されていません。",
  "No review recorded.": "レビュー記録はありません。",
  "Recorded (UTC)": "記録日時 (UTC)",
  "Appends revision {revision} with optimistic If-Match; the machine decision is never modified.":
    "楽観的 If-Match でリビジョン {revision} を追加します。機械判定は変更されません。",
  "Bounded reason (optional)": "制限付き理由（任意）",
  "No media bound to this inspection.": "この検査に紐づくメディアはありません。",
  "Enlarge media": "メディアを拡大",
  "Review recorded.": "レビューを記録しました。",
  "A newer review exists; the page was refreshed.":
    "より新しいレビューが存在するため、ページを更新しました。",
  "failed to load the inspection": "検査の読み込みに失敗しました",
  "failed to submit the review": "レビューの送信に失敗しました",

  // Review queue
  "NG and uncertain inspections awaiting append-only review. Machine outcomes are never modified; reviewed labels are shown separately.":
    "追記専用レビュー待ちの NG および不確実な検査。機械判定は変更されず、レビューラベルは別途表示されます。",
  "No inspections awaiting review.": "レビュー待ちの検査はありません。",
  "Machine result": "機械判定",
  "The original machine decision and evidence remain unchanged; this appends a reviewer disposition (revision 1 of an unreviewed inspection).":
    "元の機械判定と証拠は変更されません。レビューアー処置を追加します（未レビュー検査のリビジョン 1）。",
  "Bounded review reason (optional)": "制限付きレビュー理由（任意）",
  "Review r{revision} recorded ({disposition}).": "レビュー r{revision} を記録しました（{disposition}）。",
  "This inspection was reviewed by someone else; refresh the queue.":
    "この検査は別の担当者によってレビュー済みです。キューを更新してください。",
  "failed to load the review queue": "レビューキューの読み込みに失敗しました",

  // Review dispositions (design 24.3; labels align with edge-web)
  "Confirmed NG": "NG を確認",
  "Confirmed OK": "OK を確認",
  "Corrected NG": "NG に修正",
  Inconclusive: "判定不能",
  Reinspect: "再検査",
};
