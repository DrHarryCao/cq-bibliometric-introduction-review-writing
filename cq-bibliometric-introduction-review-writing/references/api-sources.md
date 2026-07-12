# 学术数据源策略

## 默认顺序

1. OpenAlex：主题检索、作者/机构、主题词、引文连接、OA 位置。
2. Crossref：DOI、出版元数据、许可、部分摘要与参考文献。
3. Unpaywall：已知 DOI 的合法 OA 位置。
4. Semantic Scholar：仅在配置密钥且确有补充价值时增强，不作为必需依赖。

## 凭据

- 普通用户无需手动设置环境变量。`search` 在缺少 OpenAlex Key 时自动弹出原生密码对话框，并安全保存到系统凭据库；macOS 使用钥匙串，其他系统使用 `keyring`。
- `credentials guide --open-browser` 显示申请步骤并可打开 OpenAlex 官方 API 设置页。
- `credentials setup/status/test/update/delete` 分别用于安全配置、查看掩码状态、验证额度、替换和删除。所有报告均不输出实际值。
- 官方入口：[API key](https://openalex.org/settings/api)、[用量](https://openalex.org/settings/usage)、[认证指南](https://developers.openalex.org/guides/authentication)。
- 环境变量优先于安全存储；`status` 必须显示覆盖警告，避免用户更换钥匙串后仍误用旧环境变量。
- `OPENALEX_API_KEY`、`UNPAYWALL_EMAIL`、`CROSSREF_EMAIL`、`S2_API_KEY` 环境变量仍可供自动化或高级用户临时覆盖系统凭据。

脚本不得把凭据写入项目、manifest、聊天记录、缓存键可逆文本或导出文件。遇到 429/5xx 使用指数退避并保留缓存；重复执行默认复用缓存。

## 全文

优先级为用户合法提供的本地文件 → 明确 OA 直达 PDF → 经用户确认的 OpenAlex content。不要抓取登录后页面，不要破解验证码或机构权限。OpenAlex content 可能计费，执行前必须显示文件数和估算费用。

在检索计划已确认后，可用 `search --download-oa --oa-limit N` 下载明确 OA 的直达 PDF。只有再次取得用户对文件数和费用的确认后，才可额外传入 `--allow-paid-openalex-content`；该开关不会绕过许可，只允许调用 OpenAlex 的计费 content 地址。
