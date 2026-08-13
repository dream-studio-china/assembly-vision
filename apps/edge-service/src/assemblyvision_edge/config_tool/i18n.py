"""Config tool localization (en / zh-CN / zh-HK / ja).

Message keys are English phrases, matching the edge-web/admin-web i18n
convention; each language provides the display value. English is the default.
"""

from __future__ import annotations

from typing import Literal

Lang = Literal["en", "zh-CN", "zh-HK", "ja"]

SUPPORTED_LANGS: tuple[Lang, ...] = ("en", "zh-CN", "zh-HK", "ja")
DEFAULT_LANG: Lang = "en"

_LANG_NAMES: dict[Lang, str] = {
    "en": "English",
    "zh-CN": "Simplified Chinese",
    "zh-HK": "Traditional Chinese",
    "ja": "Japanese",
}

_MESSAGES: dict[str, dict[Lang, str]] = {
    "Select language": {
        "en": "Select language",
        "zh-CN": "选择语言",
        "zh-HK": "選擇語言",
        "ja": "言語を選択",
    },
    "Select an object to edit": {
        "en": "Select an object to edit",
        "zh-CN": "选择要修改的对象",
        "zh-HK": "選擇要修改的物件",
        "ja": "編集するオブジェクトを選択",
    },
    "Product / rule": {
        "en": "Product / rule",
        "zh-CN": "产品 / 规则",
        "zh-HK": "產品 / 規則",
        "ja": "製品 / ルール",
    },
    "Camera instances (devices)": {
        "en": "Camera instances (devices)",
        "zh-CN": "相机实例（设备）",
        "zh-HK": "相機實例（設備）",
        "ja": "カメラインスタンス（デバイス）",
    },
    "Detection thresholds": {
        "en": "Detection thresholds",
        "zh-CN": "检测阈值",
        "zh-HK": "偵測閾值",
        "ja": "検出閾値",
    },
    "ROI": {
        "en": "ROI",
        "zh-CN": "ROI（感兴趣区域）",
        "zh-HK": "ROI（感興趣區域）",
        "ja": "ROI（関心領域）",
    },
    "Identity / barcode": {
        "en": "Identity / barcode",
        "zh-CN": "身份 / 条码",
        "zh-HK": "身份 / 條碼",
        "ja": "識別 / バーコード",
    },
    "Model manifests": {
        "en": "Model manifests",
        "zh-CN": "模型清单",
        "zh-HK": "模型清單",
        "ja": "モデルマニフェスト",
    },
    "Central server (.env)": {
        "en": "Central server (.env)",
        "zh-CN": "中央服务器（.env）",
        "zh-HK": "中央伺服器（.env）",
        "ja": "中央サーバー（.env）",
    },
    "Back": {
        "en": "Back",
        "zh-CN": "返回",
        "zh-HK": "返回",
        "ja": "戻る",
    },
    "Quit": {
        "en": "Quit",
        "zh-CN": "退出",
        "zh-HK": "退出",
        "ja": "終了",
    },
    "Returned to the previous menu": {
        "en": "Returned to the previous menu",
        "zh-CN": "已返回上一层菜单",
        "zh-HK": "已返回上一層選單",
        "ja": "前のメニューに戻りました",
    },
    "Add": {
        "en": "Add",
        "zh-CN": "新增",
        "zh-HK": "新增",
        "ja": "追加",
    },
    "Edit": {
        "en": "Edit",
        "zh-CN": "修改",
        "zh-HK": "修改",
        "ja": "編集",
    },
    "Delete": {
        "en": "Delete",
        "zh-CN": "删除",
        "zh-HK": "刪除",
        "ja": "削除",
    },
    "Select an action": {
        "en": "Select an action",
        "zh-CN": "选择操作",
        "zh-HK": "選擇操作",
        "ja": "操作を選択",
    },
    "Existing instances": {
        "en": "Existing instances",
        "zh-CN": "现有实例",
        "zh-HK": "現有實例",
        "ja": "既存インスタンス",
    },
    "Select an instance": {
        "en": "Select an instance",
        "zh-CN": "选择实例",
        "zh-HK": "選擇實例",
        "ja": "インスタンスを選択",
    },
    "New instance id": {
        "en": "New instance id",
        "zh-CN": "新实例 ID",
        "zh-HK": "新實例 ID",
        "ja": "新しいインスタンス ID",
    },
    "Camera source": {
        "en": "Camera source",
        "zh-CN": "相机来源",
        "zh-HK": "相機來源",
        "ja": "カメラソース",
    },
    "Required": {
        "en": "required",
        "zh-CN": "必填",
        "zh-HK": "必填",
        "ja": "必須",
    },
    "Press enter to keep": {
        "en": "press enter to keep",
        "zh-CN": "回车保持不变",
        "zh-HK": "按 Enter 保持不變",
        "ja": "Enter で現状維持",
    },
    "Creating new": {
        "en": "creating new",
        "zh-CN": "正在新建",
        "zh-HK": "正在新建",
        "ja": "新規作成中",
    },
    "Validation passed": {
        "en": "Validation passed",
        "zh-CN": "校验通过",
        "zh-HK": "驗證通過",
        "ja": "検証に合格",
    },
    "Validation failed": {
        "en": "Validation failed",
        "zh-CN": "校验失败",
        "zh-HK": "驗證失敗",
        "ja": "検証に失敗",
    },
    "Change preview": {
        "en": "Change preview",
        "zh-CN": "变更预览",
        "zh-HK": "變更預覽",
        "ja": "変更プレビュー",
    },
    "Apply changes": {
        "en": "Apply changes",
        "zh-CN": "应用变更",
        "zh-HK": "套用變更",
        "ja": "変更を適用",
    },
    "Cancel": {
        "en": "Cancel",
        "zh-CN": "取消",
        "zh-HK": "取消",
        "ja": "キャンセル",
    },
    "View full diff": {
        "en": "View full diff",
        "zh-CN": "查看完整差异",
        "zh-HK": "查看完整差異",
        "ja": "完全な差分を表示",
    },
    "Backed up": {
        "en": "Backed up",
        "zh-CN": "已备份",
        "zh-HK": "已備份",
        "ja": "バックアップ済み",
    },
    "Written": {
        "en": "Written",
        "zh-CN": "已写入",
        "zh-HK": "已寫入",
        "ja": "書き込み済み",
    },
    "Change cancelled": {
        "en": "Change cancelled",
        "zh-CN": "变更已取消",
        "zh-HK": "變更已取消",
        "ja": "変更をキャンセルしました",
    },
    "Error": {
        "en": "Error",
        "zh-CN": "错误",
        "zh-HK": "錯誤",
        "ja": "エラー",
    },
    "Warning": {
        "en": "Warning",
        "zh-CN": "警告",
        "zh-HK": "警告",
        "ja": "警告",
    },
    "Info": {
        "en": "Info",
        "zh-CN": "信息",
        "zh-HK": "資訊",
        "ja": "情報",
    },
    "No backups found": {
        "en": "No backups found",
        "zh-CN": "未找到备份",
        "zh-HK": "未找到備份",
        "ja": "バックアップが見つかりません",
    },
    "Backup history": {
        "en": "Backup history",
        "zh-CN": "备份历史",
        "zh-HK": "備份歷史",
        "ja": "バックアップ履歴",
    },
    "Rollback to backup": {
        "en": "Rollback to backup",
        "zh-CN": "回滚到此备份",
        "zh-HK": "回滾到此備份",
        "ja": "このバックアップへロールバック",
    },
    "Rollback failed": {
        "en": "Rollback failed",
        "zh-CN": "回滚失败",
        "zh-HK": "回滾失敗",
        "ja": "ロールバックに失敗",
    },
    "Rolled back": {
        "en": "Rolled back",
        "zh-CN": "已回滚",
        "zh-HK": "已回滾",
        "ja": "ロールバック済み",
    },
    "Environment": {
        "en": "Environment",
        "zh-CN": "运行环境",
        "zh-HK": "執行環境",
        "ja": "実行環境",
    },
    "development": {
        "en": "development",
        "zh-CN": "开发",
        "zh-HK": "開發",
        "ja": "開発",
    },
    "production": {
        "en": "production",
        "zh-CN": "生产",
        "zh-HK": "生產",
        "ja": "本番",
    },
    "Config file": {
        "en": "Config file",
        "zh-CN": "配置文件",
        "zh-HK": "設定檔",
        "ja": "設定ファイル",
    },
    "Central env file": {
        "en": "Central env file",
        "zh-CN": "中央环境文件",
        "zh-HK": "中央環境檔案",
        "ja": "中央環境ファイル",
    },
    "Pipeline config file": {
        "en": "Pipeline config file",
        "zh-CN": "管线配置文件",
        "zh-HK": "管線設定檔",
        "ja": "パイプライン設定ファイル",
    },
    "Required option": {
        "en": "Required option:",
        "zh-CN": "需要参数：",
        "zh-HK": "需要參數：",
        "ja": "必要なオプション：",
    },
    "No configuration changes made": {
        "en": "No configuration changes made",
        "zh-CN": "未进行配置变更",
        "zh-HK": "未進行設定變更",
        "ja": "設定の変更はありません",
    },
    "Field": {
        "en": "Field",
        "zh-CN": "字段",
        "zh-HK": "欄位",
        "ja": "フィールド",
    },
    "Value": {
        "en": "Value",
        "zh-CN": "值",
        "zh-HK": "值",
        "ja": "値",
    },
    "Invalid value": {
        "en": "Invalid value",
        "zh-CN": "无效的值",
        "zh-HK": "無效的值",
        "ja": "無効な値",
    },
    "Select a manifest": {
        "en": "Select a manifest",
        "zh-CN": "选择清单",
        "zh-HK": "選擇清單",
        "ja": "マニフェストを選択",
    },
    "product manifest": {
        "en": "product manifest",
        "zh-CN": "产品清单",
        "zh-HK": "產品清單",
        "ja": "製品マニフェスト",
    },
    "component manifest": {
        "en": "component manifest",
        "zh-CN": "组件清单",
        "zh-HK": "元件清單",
        "ja": "部品マニフェスト",
    },
    "Not found": {
        "en": "not found",
        "zh-CN": "未找到",
        "zh-HK": "未找到",
        "ja": "見つかりません",
    },
    "No instances configured": {
        "en": "No instances configured",
        "zh-CN": "未配置实例",
        "zh-HK": "未設定實例",
        "ja": "インスタンスが設定されていません",
    },
    "Cannot edit a flat single-instance config; use the multi-instance form": {
        "en": "Cannot edit a flat single-instance config; use the multi-instance form",
        "zh-CN": "无法编辑单实例配置，请使用多实例格式",
        "zh-HK": "無法編輯單一實例設定，請使用多實例格式",
        "ja": "フラットな単一インスタンス設定は編集できません。複数インスタンス形式を使用してください",
    },
    "Config file does not exist": {
        "en": "Config file does not exist",
        "zh-CN": "配置文件不存在",
        "zh-HK": "設定檔不存在",
        "ja": "設定ファイルが存在しません",
    },
    "Would you like to create it": {
        "en": "Would you like to create it?",
        "zh-CN": "是否创建？",
        "zh-HK": "是否建立？",
        "ja": "作成しますか？",
    },
    "Yes": {
        "en": "Yes",
        "zh-CN": "是",
        "zh-HK": "是",
        "ja": "はい",
    },
    "No": {
        "en": "No",
        "zh-CN": "否",
        "zh-HK": "否",
        "ja": "いいえ",
    },
    "Skipped validation; no config file": {
        "en": "Skipped validation; no config file",
        "zh-CN": "跳过校验：无配置文件",
        "zh-HK": "跳過驗證：無設定檔",
        "ja": "検証をスキップ：設定ファイルがありません",
    },
    "Apply anyway": {
        "en": "Apply anyway?",
        "zh-CN": "仍然应用？",
        "zh-HK": "仍然套用？",
        "ja": "それでも適用しますか？",
    },
    "Rule id": {
        "en": "Rule id",
        "zh-CN": "规则 ID",
        "zh-HK": "規則 ID",
        "ja": "ルールID",
    },
    "Rule version": {
        "en": "Rule version",
        "zh-CN": "规则版本",
        "zh-HK": "規則版本",
        "ja": "ルールバージョン",
    },
    "Product type": {
        "en": "Product type",
        "zh-CN": "产品类型",
        "zh-HK": "產品類型",
        "ja": "製品タイプ",
    },
    "Barcode required": {
        "en": "Barcode required",
        "zh-CN": "条码必填",
        "zh-HK": "條碼必填",
        "ja": "バーコード必須",
    },
    "Compatible component model versions": {
        "en": "Compatible component model versions",
        "zh-CN": "兼容组件模型版本",
        "zh-HK": "兼容元件模型版本",
        "ja": "互換コンポーネントモデルバージョン",
    },
    "FPS": {
        "en": "FPS",
        "zh-CN": "帧率",
        "zh-HK": "幀率",
        "ja": "FPS",
    },
    "Loop": {
        "en": "Loop",
        "zh-CN": "循环",
        "zh-HK": "循環",
        "ja": "ループ",
    },
    "Image folder path": {
        "en": "Image folder path",
        "zh-CN": "图片文件夹路径",
        "zh-HK": "圖片資料夾路徑",
        "ja": "画像フォルダパス",
    },
    "Video path": {
        "en": "Video path",
        "zh-CN": "视频路径",
        "zh-HK": "影片路徑",
        "ja": "ビデオパス",
    },
    "Device index or path": {
        "en": "Device index or path",
        "zh-CN": "设备索引或路径",
        "zh-HK": "設備索引或路徑",
        "ja": "デバイス索引またはパス",
    },
    "RTSP URL": {
        "en": "RTSP URL",
        "zh-CN": "RTSP 地址",
        "zh-HK": "RTSP 地址",
        "ja": "RTSP URL",
    },
    "HTTP image URL": {
        "en": "HTTP image URL",
        "zh-CN": "HTTP 图片地址",
        "zh-HK": "HTTP 圖片地址",
        "ja": "HTTP 画像 URL",
    },
    "Camera serial": {
        "en": "Camera serial",
        "zh-CN": "相机序列号",
        "zh-HK": "相機序號",
        "ja": "カメラシリアル",
    },
    "GenTL producer (.cti)": {
        "en": "GenTL producer (.cti)",
        "zh-CN": "GenTL 生产者（.cti）",
        "zh-HK": "GenTL 生產者（.cti）",
        "ja": "GenTL プロデューサー（.cti）",
    },
    "Trigger mode": {
        "en": "Trigger mode",
        "zh-CN": "触发模式",
        "zh-HK": "觸發模式",
        "ja": "トリガーモード",
    },
    "Pixel format": {
        "en": "Pixel format",
        "zh-CN": "像素格式",
        "zh-HK": "像素格式",
        "ja": "ピクセル形式",
    },
    "Exposure (us)": {
        "en": "Exposure (us)",
        "zh-CN": "曝光（微秒）",
        "zh-HK": "曝光（微秒）",
        "ja": "露光（µs）",
    },
    "Gain (dB)": {
        "en": "Gain (dB)",
        "zh-CN": "增益（dB）",
        "zh-HK": "增益（dB）",
        "ja": "ゲイン（dB）",
    },
    "Packet size": {
        "en": "Packet size",
        "zh-CN": "数据包大小",
        "zh-HK": "資料包大小",
        "ja": "パケットサイズ",
    },
    "Product confidence threshold": {
        "en": "Product confidence threshold",
        "zh-CN": "产品置信度阈值",
        "zh-HK": "產品置信度閾值",
        "ja": "製品信頼度閾値",
    },
    "Product IOU threshold": {
        "en": "Product IOU threshold",
        "zh-CN": "产品 IOU 阈值",
        "zh-HK": "產品 IOU 閾值",
        "ja": "製品 IOU 閾値",
    },
    "Component IOU threshold": {
        "en": "Component IOU threshold",
        "zh-CN": "组件 IOU 阈值",
        "zh-HK": "元件 IOU 閾值",
        "ja": "部品 IOU 閾値",
    },
    "ROI margin X ratio": {
        "en": "ROI margin X ratio",
        "zh-CN": "ROI X 边距比例",
        "zh-HK": "ROI X 邊距比例",
        "ja": "ROI X マージン比率",
    },
    "ROI margin Y ratio": {
        "en": "ROI margin Y ratio",
        "zh-CN": "ROI Y 边距比例",
        "zh-HK": "ROI Y 邊距比例",
        "ja": "ROI Y マージン比率",
    },
    "ROI minimum area (pixels)": {
        "en": "ROI minimum area (pixels)",
        "zh-CN": "ROI 最小面积（像素）",
        "zh-HK": "ROI 最小面積（像素）",
        "ja": "ROI 最小面積（ピクセル）",
    },
    "ROI minimum expanded area retained": {
        "en": "ROI minimum expanded area retained",
        "zh-CN": "ROI 最小保留扩展面积",
        "zh-HK": "ROI 最小保留擴展面積",
        "ja": "ROI 最小拡張面積保持",
    },
    "ROI normalize perspective": {
        "en": "ROI normalize perspective",
        "zh-CN": "ROI 透视归一化",
        "zh-HK": "ROI 透視歸一化",
        "ja": "ROI 透視正規化",
    },
    "Barcode identity enabled": {
        "en": "Barcode identity enabled",
        "zh-CN": "启用条码身份",
        "zh-HK": "啟用條碼身份",
        "ja": "バーコード識別有効",
    },
    "Barcode identity required": {
        "en": "Barcode identity required",
        "zh-CN": "条码身份必填",
        "zh-HK": "條碼身份必填",
        "ja": "バーコード識別必須",
    },
    "Allowed symbologies": {
        "en": "Allowed symbologies",
        "zh-CN": "允许的码制",
        "zh-HK": "允許的碼制",
        "ja": "許可シンボロジー",
    },
    "Barcode mapping file": {
        "en": "Barcode mapping file",
        "zh-CN": "条码映射文件",
        "zh-HK": "條碼映射檔案",
        "ja": "バーコードマッピングファイル",
    },
    "Model version label": {
        "en": "Model version label",
        "zh-CN": "模型版本标签",
        "zh-HK": "模型版本標籤",
        "ja": "モデルバージョンラベル",
    },
    "Class names (comma separated)": {
        "en": "Class names (comma separated)",
        "zh-CN": "类别名称（逗号分隔）",
        "zh-HK": "類別名稱（逗號分隔）",
        "ja": "クラス名（カンマ区切り）",
    },
    "Semantic version": {
        "en": "Semantic version",
        "zh-CN": "语义版本",
        "zh-HK": "語義版本",
        "ja": "セマンティックバージョン",
    },
    "Artifact URI": {
        "en": "Artifact URI",
        "zh-CN": "工件 URI",
        "zh-HK": "工件 URI",
        "ja": "アーティファクト URI",
    },
    "Artifact SHA-256": {
        "en": "Artifact SHA-256",
        "zh-CN": "工件 SHA-256",
        "zh-HK": "工件 SHA-256",
        "ja": "アーティファクト SHA-256",
    },
    "Artifact size (bytes)": {
        "en": "Artifact size (bytes)",
        "zh-CN": "工件大小（字节）",
        "zh-HK": "工件大小（位元組）",
        "ja": "アーティファクトサイズ（バイト）",
    },
    "Database URL": {
        "en": "Database URL",
        "zh-CN": "数据库地址",
        "zh-HK": "資料庫地址",
        "ja": "データベースURL",
    },
    "MinIO endpoint": {
        "en": "MinIO endpoint",
        "zh-CN": "MinIO 端点",
        "zh-HK": "MinIO 端點",
        "ja": "MinIO エンドポイント",
    },
    "MinIO access key": {
        "en": "MinIO access key",
        "zh-CN": "MinIO 访问密钥",
        "zh-HK": "MinIO 存取金鑰",
        "ja": "MinIO アクセスキー",
    },
    "MinIO secret key": {
        "en": "MinIO secret key",
        "zh-CN": "MinIO 秘密密钥",
        "zh-HK": "MinIO 秘密金鑰",
        "ja": "MinIO シークレットキー",
    },
    "MinIO bucket": {
        "en": "MinIO bucket",
        "zh-CN": "MinIO 存储桶",
        "zh-HK": "MinIO 儲存桶",
        "ja": "MinIO バケット",
    },
    "MinIO secure (TLS)": {
        "en": "MinIO secure (TLS)",
        "zh-CN": "MinIO 安全连接（TLS）",
        "zh-HK": "MinIO 安全連線（TLS）",
        "ja": "MinIO セキュア（TLS）",
    },
    "Administrator token": {
        "en": "Administrator token",
        "zh-CN": "管理员令牌",
        "zh-HK": "管理員令牌",
        "ja": "管理者トークン",
    },
    "Device upload token": {
        "en": "Device upload token",
        "zh-CN": "设备上传令牌",
        "zh-HK": "設備上傳令牌",
        "ja": "デバイスアップロードトークン",
    },
    "Secure session cookies": {
        "en": "Secure session cookies",
        "zh-CN": "安全会话 Cookie",
        "zh-HK": "安全工作階段 Cookie",
        "ja": "セキュアセッションCookie",
    },
    "Rate limit per minute": {
        "en": "Rate limit per minute",
        "zh-CN": "每分钟限流",
        "zh-HK": "每分鐘限流",
        "ja": "毎分レート制限",
    },
    "Admin session TTL (minutes)": {
        "en": "Admin session TTL (minutes)",
        "zh-CN": "管理员会话 TTL（分钟）",
        "zh-HK": "管理員工作階段 TTL（分鐘）",
        "ja": "管理者セッションTTL（分）",
    },
    "PostgreSQL user": {
        "en": "PostgreSQL user",
        "zh-CN": "PostgreSQL 用户",
        "zh-HK": "PostgreSQL 用戶",
        "ja": "PostgreSQL ユーザー",
    },
    "PostgreSQL password": {
        "en": "PostgreSQL password",
        "zh-CN": "PostgreSQL 密码",
        "zh-HK": "PostgreSQL 密碼",
        "ja": "PostgreSQL パスワード",
    },
    "PostgreSQL database": {
        "en": "PostgreSQL database",
        "zh-CN": "PostgreSQL 数据库",
        "zh-HK": "PostgreSQL 資料庫",
        "ja": "PostgreSQL データベース",
    },
    "MinIO root user": {
        "en": "MinIO root user",
        "zh-CN": "MinIO 根用户",
        "zh-HK": "MinIO 根用戶",
        "ja": "MinIO ルートユーザー",
    },
    "MinIO root password": {
        "en": "MinIO root password",
        "zh-CN": "MinIO 根密码",
        "zh-HK": "MinIO 根密碼",
        "ja": "MinIO ルートパスワード",
    },
    "MinIO bucket (compose)": {
        "en": "MinIO bucket (compose)",
        "zh-CN": "MinIO 存储桶（compose）",
        "zh-HK": "MinIO 儲存桶（compose）",
        "ja": "MinIO バケット（compose）",
    },
}


def lang_name(lang: Lang) -> str:
    """Human-readable language name in its own language."""
    return _LANG_NAMES[lang]


def t(lang: Lang, key: str) -> str:
    """Translate ``key``; unknown keys fall back to the English text."""
    entry = _MESSAGES.get(key)
    if entry is None:
        return key
    return entry.get(lang) or entry["en"]
