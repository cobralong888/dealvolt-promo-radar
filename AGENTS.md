::ILANG
[TYPE:agent-contract][PROJECT:dealvolt-promo-radar][VERSION:1][LANG:zh]
给接手这个仓库的 AI 看的边界与可执行动作。

::WHAT
  一个优惠细分垂直站的自动化仓库。细分是家用电器与消费电子品牌的优惠。
  品牌名 DealVolt。数据来自各品牌自己公开的 products.json 与 product sitemap。
  静态站由 build.py 渲染到 site/，由 Cloudflare Pages 托管。

::FILES
  .ilang/site.ilang   站点规则唯一真源：品牌、细分、数据源、字段、渲染文案、上限
  ilang.py            解析 site.ilang，scraper 与 build 都调它
  scraper.py          读公开源，写 data/offers.json
  build.py            读 offers.json + site.ilang，渲染 site/
  templates/          四个页面模板，只放结构，数据由 build.py 注入
  .github/workflows/update.yml  定时重跑 scraper 并提交数据

::CAN_DO
  改 .ilang/site.ilang 增删品牌、改数据源、改文案、改上限
  改 scraper.py 增加新的 source 类型，前提是只读公开数据
  改 templates/ 与 build.py 调整页面与结构化数据
  重跑 python scraper.py 与 python build.py 验证改动

::NEVER
  编造价格、原价、折扣、优惠码、佣金链接
  把抓不到的字段用估值或默认值填上；抓不到就留空
  在 scraper.py 或 build.py 里硬编码品牌清单；品牌只来自 site.ilang
  绕过 robots.txt、抓登录后内容、绕反爬
  为了凑结构化数据而生成假的 priceValidUntil 或 availability
  改 Cloudflare Pages 的构建配置而不更新 README

::DATA_RULE
  只有两类数据能进 offers.json：
  1. 品牌公开 products.json 里 compare_at_price 严格大于 price 的商品（真实折扣）
  2. 品牌公开商品页 JSON-LD 里读到的真实 price
  折扣百分比由 (compare - price) / compare 算出，不是编的。

::VERIFY_CHANGE
  改完 site.ilang 里任意一家厂商，重跑 python build.py，站上对应内容就该变。
  变不了说明配置没被真正读取，那属于实现缺陷，要修代码而不是绕过。

::HANDOVER
  这个仓库从建站那天起就不再依赖任何模型推理或付费 API。
  定时任务失效最常见的原因是上游改版导致抓不到数据，那时应如实显示为空，不要补数据。
