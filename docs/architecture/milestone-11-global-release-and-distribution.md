# 第十一里程碑：中国内地与海外发布、资质和渠道计划

> 核验日期：2026-09-01（Asia/Shanghai）。本文是发布准备清单，不是法律意见，也不表示
> 已取得任何资质、备案、许可证、商店账号或专业审查结论。“海外”必须在 11A 变成明确的
> 国家/地区允许列表；不存在一张可以覆盖所有国家的“全球上线证”。

## 1. 总体发布策略

这里必须先区分三种容易都被叫作“网页版”的形态：

| 形态 | 当前规划 | 资质边界 |
| --- | --- | --- |
| 浏览器承载的本地应用 | 一行命令启动服务并打开 loopback 本地页面，是当前确认的产品入口方向 | 本地页面本身不是公网网站；仍须核对软件分发、签名、更新、隐私和其访问的云 API |
| 官网/下载与支持门户 | 尚未建立，用于下载、文档、隐私、支持和安全联系 | 域名、托管地区、ICP备案/许可分类、公安备案、隐私和消费者信息按实际功能核对 |
| 公网托管 Web 服务 | 可选，尚未确认是否作为首发形态 | 多用户认证、数据托管、跨境、内容/AI、支持、安全、容量和地区放行必须独立通过 |

因此“一行命令打开本地网页”不表示已经在中国内地或海外上线网站，也不能替代下载官网或云端
账号/保存 API 的资质审查。11A 必须明确首发究竟包含哪几种形态，未选择的形态默认不发布。

第十一里程碑按渠道独立放行：

1. 中国内地网页版；
2. 海外网页版；
3. GitHub → Gitee 代码镜像；
4. Android 官网下载安装包；
5. Microsoft Store；
6. Apple App Store。

当前产品入口优先级是一行命令打开的本地网页；第十一里程碑的首个公网渠道应先建设其下载/
支持官网和实际启用的云 API。应用商店和 Android 包只有在实际客户端、签名、更新和隐私行为
稳定后才能申报，不得用网页壳或未来计划冒充已具备 App 上架条件。

中国内地和海外可以共用产品代码与技能包标准，但不应默认共用身份、数据库、日志、支持队列、
外部 AI 配置或社区审核结果。是否采用区域部署和数据隔离由 11A 决定。

## 2. 先准备的主体与权利证明

无论哪个渠道，至少需要准备以下真实、可核验材料；个人和企业要求不同：

| 材料 | 用途 | 状态 |
| --- | --- | --- |
| 运营主体身份证明 | 个人身份证件，或企业营业执照、统一社会信用代码、法定代表人/授权人材料 | 待决定主体 |
| 联系与地址证明 | 域名、备案、商店验证、隐私/支持/侵权通知 | 待准备，禁止写虚假地址 |
| 域名注册证明与 DNS 控制 | ICP、身份回调、商店隐私政策 URL、邮件和安全验证 | 官网未建立 |
| 项目著作权链 | 自有代码清单、员工/外包/贡献者授权、第三方依赖和素材许可证 | 部分已有，需审计 |
| 软件著作权登记 | 中国自愿登记，通常不是运行软件的前置许可，但可用于权属、备案和争议证明 | 强烈建议 |
| 商标申请/注册 | “云奕学”、英文名、Logo 及对应软件、教育、SaaS/社区服务类别 | 尚未授权制作/申请 |
| 隐私与服务联系 | 公开、长期可用的隐私、安全、支持和侵权渠道 | 待确认 |
| 银行、税务与结算 | 只有收费、商店付款或商业许可时需要 | 当前免费验证，不启用 |

以企业名义长期运营、签订供应商合同、申请经营许可、处理社区投诉和进行商业授权通常比个人
身份更可持续，但设立何种主体涉及税务和责任，必须由项目所有者结合专业意见决定。

## 3. 中国内地官网、公网 Web 与云 API

### 3.1 固定需要或由部署方式直接触发

| 项目 | 何时需要 | 主要材料/结果 |
| --- | --- | --- |
| 域名实名与 HTTPS | 使用自有官网 | 实名域名、DNS 控制、TLS 证书、域名续费和失效预案 |
| ICP 备案 | 网站部署在中国内地服务器或使用要求备案的内地接入/CDN | 主体证件、域名、接入商、服务内容、负责人和备案号；网站展示备案号 |
| ICP 经营许可证 | 在中国境内有偿提供经营性互联网信息服务且分类触发 | 企业主体、业务/技术/安全制度等；不能用普通备案代替 |
| 公安联网备案 | 按适用规则在网站联网后办理 | 全国互联网安全管理服务平台登记并展示公安备案信息 |
| App 备案 | 未来 Android/iOS 等 App 向中国内地用户提供互联网信息服务 | 通过接入/分发渠道提交主体、域名、SDK/服务等信息；与网站备案不是同一个“自动完成”结论 |
| 网络安全等级保护 | 系统定级结果达到备案要求时，公开多用户系统通常必须专门评估 | 定级、备案、测评、整改和持续复核；不得自行宣称等级 |

如果官网、公网 Web 或云 API 继续只部署在新加坡且不使用中国内地接入资源，通常不能仅为了加速而取得普通内地
接入备案；但面向中国内地用户仍要遵守适用的个人信息、数据、内容、消费者和 AI 规则，且可用性
不能保证。未来 Apple 中国大陆区也可能按 App 类型要求有效 ICP 备案号，不能用海外服务器规避
商店字段。

### 3.2 所有真实用户服务都需要的合规文件

- 中文隐私政策、服务条款、儿童/未成年人说明、Cookie/SDK/权限清单；
- 个人信息处理规则、最小必要清单、同意记录、查阅/复制/更正/删除/注销流程；
- 个人信息保护影响评估、处理活动记录、供应商/受托处理协议和安全事件预案；
- 用户生成文本、代码、作品、支持材料和社区资源的用途、保留、投诉与删除规则；
- 账号实名要求的适用性判断；不需要实名的场景不得超量收集身份证明；
- 数据分类分级、访问控制、备份、日志、漏洞、应急和人员权限制度；
- 向新加坡或其他境外位置发送中国内地个人信息时的数据出境路径、单独同意和记录。

数据出境不能只看人数。是否属于重要数据、敏感个人信息、关键信息基础设施运营者，以及当年
累计数量都会改变安全评估、标准合同或认证要求。2024 年《促进和规范数据跨境流动规定》提供
若干豁免和数量门槛，但不能据此默认本项目豁免。

### 3.3 按功能触发的专项资质或评估

| 功能 | 可能触发 | 当前处理 |
| --- | --- | --- |
| 对公众提供生成式 AI | 《生成式人工智能服务管理暂行办法》中的服务协议、输入/记录保护、内容处置；具有舆论属性或社会动员能力时的安全评估与算法备案 | 第十一里程碑前保持真实 AI 关闭，先做专业分类 |
| 个性化推荐/排序 | 算法推荐透明、关闭/删除标签、未成年人保护；具有舆论属性或社会动员能力时备案 | 学习排序与社区推荐分别评估，不能因“教育”自动豁免 |
| 社区投稿、评论、资源市场 | 账号、内容审核、举报、侵权投诉、恶意代码、记录留存；可能涉及跟帖评论、网络出版等专项规则 | 社区放到第十四里程碑，不随网页版自动开放 |
| 收费课程/会员/SaaS | 市场主体、税务、消费者、自动续费、支付、ICP 经营许可及教育分类 | 当前不收费，后续单独授权 |
| 学历、K12、职业培训或证书 | 教育主管部门许可、广告和证书表述可能变化 | 当前只作自学工具，不宣传学历/资格认证 |
| 新闻、出版、音视频、网络文化 | 相应主管部门前置审批或许可证 | 首版排除这些业务，不以社区名义绕过 |
| 未成年人 | 未成年人网络保护、监护人同意、模式/时长/内容和个人信息专门规则 | 推荐首批只接受成年人，待确认 |

软件著作权登记、商标注册通常是权利保护而不是一般网站上线许可证；但缺少它们会增加商店审核、
镜像冒用和维权难度。不得把“已登记著作权”描述成产品安全、内容正确或行政准入批准。

## 4. 海外官网、公网 Web 与云 API

海外没有统一资质清单。11A 必须建立国家/地区允许列表，未完成评估的地区默认不主动营销或
开放注册。所有地区至少需要运营主体、隐私政策、服务条款、可接受使用规则、支持/安全/侵权
联系、数据处理者清单、账号删除、消费者信息、税务分类和跨境传输记录。

| 地区 | 主要额外准备 | 说明 |
| --- | --- | --- |
| 欧盟/欧洲经济区 | GDPR 处理依据、透明度、权利、RoPA、DPA、DPIA（高风险时）、SCC/传输评估、Cookie 选择；欧盟代表/DPO 按条件；社区服务评估 DSA | Apple 还要求申报 DSA trader 状态 |
| 英国 | UK GDPR、Data Protection Act、PECR Cookie/营销、跨境机制；英国代表、ICO fee/DPO 按条件；社区评估 Online Safety Act | 不能把欧盟文件直接改标题复用 |
| 美国 | 联邦与州隐私/消费者/数据泄漏规则；面向 13 岁以下儿童时 COPPA；社区版权安全港需评估 DMCA agent；州税和商业注册按活动判断 | 没有一张“美国 GDPR 证书” |
| 加拿大 | PIPEDA 及适用省级隐私法、跨境透明和泄漏处理 | 省份和业务性质会改变适用规则 |
| 澳大利亚 | Privacy Act/APP 的主体门槛和例外、隐私政策、跨境披露与泄漏 | 小企业例外不能未经核验直接使用 |
| 新加坡 | PDPA 责任、公开 DPO 联系、目的/同意、跨境和泄漏；同时核对服务器/运营关系 | 服务器在新加坡不等于自动合规 |
| 日本 | APPI、跨境提供、第三方提供记录和泄漏 | 日语告知和本地联系按实际发布决定 |

首发“全球可访问”不应自动等于“全球提供服务”。可以先选择少量法域、限定成年人、禁用社区和
真实 AI，积累运营能力后再逐区扩展。

## 5. Apple App Store

未来提交 iOS/iPadOS/macOS App 前至少准备：

- Apple Developer Program 个人或组织账号；组织账号需要真实法人主体、授权人、组织身份
  和 Apple 要求的企业验证材料；
- App ID、证书/签名、描述文件、App Store Connect 记录、支持 URL 和长期可访问隐私政策 URL；
- App Privacy 数据披露、第三方 SDK 清单/隐私 manifest、required-reason API 和 SDK 签名要求；
- App 内账号创建时的 App 内账号删除；注销必须真实删除或解释依法保留范围；
- 使用第三方社交登录时核对 Sign in with Apple 要求；
- 年龄分级、内容权利、加密出口合规、地区可用性、辅助功能和审核测试账号；
- 用户生成内容/社区功能的过滤、举报、屏蔽、联系和及时处置；
- 中国大陆区适用的 ICP 备案号及其他许可证字段，且信息与工信部记录一致；
- 欧盟区 DSA trader/non-trader 信息及平台要求的联系展示；
- 销售数字内容时的 In-App Purchase、税务和商业主体方案。

Apple 审核通过不是中国行政许可、海外隐私合规或内容绝对安全的证明。个人开发者账号会显示
个人身份相关的公开信息，组织账号则要求真实组织验证，必须在创建账号前决定发布主体。

## 6. Microsoft Store

未来提交 Windows App 前至少准备：

- Partner Center 的 Individual 或 Company 开发者账号；截至核验日官方新流程称两类账号均
  无注册费，但费用政策必须在真实创建前重新核验；
- 个人政府签发身份证件和自拍验证，或公司营业/注册、域名工作邮箱、授权人和补充文件；
- 准确、持续可用的支持联系方式和商店展示主体；
- MSIX/适用包格式、包身份、签名、自动更新/回滚、认证报告和测试账号；
- 收集或传输个人信息时的隐私政策 URL、数据权利和最小权限；
- IARC 年龄分级、内容权利、第三方组件、无障碍、UGC、儿童安全和 live generative AI 规则；
- 付费时的税务、付款资料、价格、退款和消费者信息。

个人账号不能冒充公司品牌；如果计划以“云奕学”组织长期发布并签订商业许可，应先比较公司
账号的公开身份、验证成本和责任。

## 7. Android 官网分发

不通过应用商店不等于没有义务。官网直接下载至少需要：

- 与发布主体绑定并离线保护的 Android 签名密钥，明确轮换/遗失/泄漏方案；
- HTTPS 下载、版本化 APK、SHA-256 校验、签名验证说明、SBOM/第三方许可证和恶意软件扫描；
- 应用内安全更新、强制最低安全版本、回滚和撤回机制；
- 官网主体、隐私政策、服务条款、支持、安全报告、账号删除和权限/SDK 清单；
- 面向中国内地用户时完成适用 App 备案，并核对实际接入、域名和分发方式；
- 明确“允许安装未知来源”的风险说明，禁止诱导关闭系统安全保护；
- 不把 APK 放入 Git/Gitee 源码镜像代替受控发布制品和签名验证。

## 8. GitHub 到 Gitee 镜像

镜像自有代码通常不需要单独行政许可证，但必须先证明有权在两个平台分发所有代码、文档、
图片、测试数据、技能内容和第三方材料。

推荐首版规则：

- GitHub 为唯一权威源，Gitee 为自动或人工验证的只读镜像；
- 镜像精确提交 SHA、标签、Release 元数据、许可证和 Required Notice；
- 默认不镜像 Issues、PR 评论、私密安全报告、Actions 日志、Secrets、用户数据或下载统计；
- 推送前执行密钥、个人信息、大文件、第三方许可证和受管内容摘要检查；
- Gitee README 显示权威仓库、同步时间、提交 SHA、问题反馈和安全私密入口；
- 不允许两端同时接受代码后再无审查自动合并，避免历史分叉和供应链污染；
- 单独核对 GitHub/Gitee 条款、组织实名、API/机器人限制、频率和仓库存储配额；
- 商标、源码和社区资源使用不同许可证时，在仓库和包级清楚区分。

## 9. 知识产权与防止未授权商业化

建议采用“非商业源码 + 单独商业许可 + 用户成果明确保留”的组合：

- 保持当前 PolyForm Noncommercial 适用于项目所有者代码和文档；
- 分发二进制时增加不冲突的 EULA 和 Required Notice，不得事后改写已发布版本的许可；
- 提供商业许可联系和可授权范围，但未确定价格前不承诺自动购买；
- 明确禁止未经许可的收费托管、白标、再销售、捆绑、商业培训平台集成和移除权利标识；
- 明确允许用户把自己学会的能力和自己创作的代码/作品用于就业、接单或销售；
- 第三方依赖、技能来源和社区作者内容继续适用各自许可证，项目所有者不能超范围再授权；
- 未来接受贡献前选择 DCO 或 CLA；如希望对贡献做商业双重许可，CLA 必须事先明确授权；
- 申请“云奕学”文字/图形商标并发布商标政策后，才能更有力处理镜像冒用和兼容性误导。

违法使用条款应禁止攻击、恶意代码、侵权、骚扰、欺诈、规避权限和违法内容，并允许暂停服务
或资源下架；它不能把用户的一切行为风险转嫁给用户，也不能免除平台收到有效通知后的义务。

## 10. 第十一里程碑分阶段门禁

| 阶段 | 输出 | 放行条件 |
| --- | --- | --- |
| 11A | 主体、法域、年龄、模式、数据位置和资质分类 | 专业复核路径、预算和允许列表确认 |
| 11B | 许可证、EULA、条款、隐私、AUP、商标、贡献和投诉包 | 权利链与第三方许可证审计通过 |
| 11C | 中国/海外官网、公网 Web 与云 API 候选 | 先确认实际形态，再使备案/许可、隐私、数据区域、支持、安全和容量分别通过 |
| 11D | Gitee 只读镜像 | SHA/标签一致、无敏感状态、许可证与来源正确 |
| 11E | Android 官网分发候选 | App 备案、签名、更新、撤回、官网和隐私通过 |
| 11F | Microsoft Store 候选 | 账号、身份、包、隐私、分级、支持和认证通过 |
| 11G | Apple Store 候选 | 账号、隐私、删除、UGC、ICP/地区、分级和审核材料通过 |
| 11H | 渠道逐项 go/no-go | 无严重/高风险问题，费用、支持、回滚和项目所有者授权完整 |

任一渠道通过不自动放行其他渠道。第十一里程碑不得在第十里程碑界面与第九里程碑门禁回归
完成前公开发布。

## 11. 官方来源（核验于 2026-09-01）

中国内地：

- [《互联网信息服务管理办法》](https://www.gov.cn/gongbao/content/2011/content_1860864.htm)
- [《非经营性互联网信息服务备案管理办法》](https://www.gov.cn/gongbao/content/2005/content_93018.htm)
- [工信部 ICP/IP 地址/域名信息备案管理系统](https://beian.miit.gov.cn/)
- [全国互联网安全管理服务平台](https://beian.mps.gov.cn/)
- [《中华人民共和国个人信息保护法》](https://www.npc.gov.cn/npc/c2/c30834/202108/t20210820_313088.html)
- [《促进和规范数据跨境流动规定》](https://www.cac.gov.cn/2024-03/22/c_1712776611775634.htm)
- [《生成式人工智能服务管理暂行办法》](https://www.cac.gov.cn/2023-07/13/c_1690898327029107.htm)
- [《互联网信息服务算法推荐管理规定》](https://www.cac.gov.cn/2022-01/04/c_1642894606364259.htm)

Apple 与 Microsoft：

- [Apple Developer Program enrollment](https://developer.apple.com/programs/enroll/)
- [Apple App Review Guidelines](https://developer.apple.com/app-store/review/guidelines/)
- [Apple App information：China mainland ICP 与隐私政策字段](https://developer.apple.com/help/app-store-connect/reference/app-information/app-information/)
- [Apple App 内账号删除要求](https://developer.apple.com/support/offering-account-deletion-in-your-app/)
- [Apple App Privacy](https://developer.apple.com/help/app-store-connect/manage-app-information/manage-app-privacy/)
- [Apple 第三方 SDK 要求](https://developer.apple.com/support/third-party-SDK-requirements/)
- [Apple 欧盟 DSA trader 要求](https://developer.apple.com/help/app-store-connect/manage-compliance-information/manage-european-union-digital-services-act-trader-requirements/)
- [Microsoft Partner Center 开发者账号](https://learn.microsoft.com/en-us/windows/apps/publish/partner-center/open-a-developer-account)
- [Microsoft Store Policies](https://learn.microsoft.com/en-us/windows/apps/publish/store-policies)
- [Microsoft App certification](https://learn.microsoft.com/en-us/windows/apps/publish/publish-your-app/app-certification-process)
- [Microsoft IARC age ratings](https://learn.microsoft.com/en-us/windows/apps/publish/publish-your-app/age-ratings)

海外基础规则入口：

- [欧盟数据保护法律框架](https://commission.europa.eu/law/law-topic/data-protection/data-protection-eu_en)
- [欧盟 Digital Services Act](https://digital-strategy.ec.europa.eu/en/policies/digital-services-act-package)
- [英国 ICO：UK GDPR](https://ico.org.uk/for-organisations/uk-gdpr-guidance-and-resources/)
- [美国 FTC：COPPA](https://www.ftc.gov/legal-library/browse/rules/childrens-online-privacy-protection-rule-coppa)
- [加拿大隐私专员：PIPEDA](https://www.priv.gc.ca/en/privacy-topics/privacy-laws-in-canada/the-personal-information-protection-and-electronic-documents-act-pipeda/)
- [澳大利亚 OAIC：Australian Privacy Principles](https://www.oaic.gov.au/privacy/australian-privacy-principles)
- [日本个人信息保护委员会：Laws and Policies](https://www.ppc.go.jp/en/legal/)
- [GitHub Terms of Service](https://docs.github.com/en/site-policy/github-terms/github-terms-of-service)
- [Gitee 网站使用条款](https://gitee.com/terms)

官方页面、费用和平台政策会变化。11A、真实账号创建和每次提交前都必须重新核验；本清单不应
被描述为“已穷尽全球全部法律”或专业人士的最终结论。
