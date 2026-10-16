<p align="center">
  <img src="docs/media/cover.png" alt="降噪星图：从市场关系，走进公司的生意。A股公司与行业知识阅读工具。" width="100%">
</p>

<p align="center">
  <strong>把公司做什么、靠什么赚钱、和谁有关，放回同一张图里。</strong><br>
  面向 A 股公司学习、行业研究与知识可视化的开源项目。
</p>

<p align="center">
  <a href="#先看一遍产品"><img src="docs/media/button-tour.svg" alt="观看产品演示" height="36"></a>
  <a href="https://github.com/ZHY999999999/jiangzao-xingtu-open-source/issues/new?template=use-case.yml"><img src="docs/media/button-feedback.svg" alt="聊聊你的使用场景" height="36"></a>
  <a href="https://github.com/ZHY999999999"><img src="docs/media/button-follow.svg" alt="关注作者的后续项目" height="36"></a>
</p>

<p align="center"><sub>MIT 代码开源 · React / TypeScript / Three.js · 中文优先</sub></p>

> **先说明当前状态：** 原在线服务已经停止。本仓库开放源码与已收录的编辑内容，**不含完整运行数据，clone 后不能直接构建完整网站**。下方为已验收版本的真实界面展示，截图记录于 2026 年 10 月，并非实时行情。

## 先看一遍产品

<img src="docs/media/product-tour.gif" alt="真实界面轮播：市场星图首页、公司目录、公司生意概览、展开原文出处" width="100%">

*真实界面截图制作的循环导览；用于展示产品结构，不是实时操作录像。*

| 从哪里开始 | 你能看什么 |
| --- | --- |
| **01 · 看关系** | 从市场星图认识行业、概念与公司之间的联系。 |
| **02 · 找公司** | 通过公司目录与搜索，进入具体公司的知识档案。 |
| **03 · 读生意** | 先看卖什么、谁买单、靠什么赚钱，再展开业务与经营变化。 |
| **04 · 回到出处** | 在已收录页面展开报告原文与引用线索，继续核对判断。 |

<details>
<summary><strong>展开查看高清界面</strong></summary>

**市场星图入口**

![市场星图首页](docs/media/home.png)

**公司目录**

![公司目录](docs/media/companies.png)

**公司生意概览**

![公司生意概览](docs/media/company.png)

**展开原文出处**

![原文出处](docs/media/evidence.png)

</details>

## 为什么做星图

看公司时，信息往往散在行情页、财报与行业资料里。我们想把这些入口连起来：**先看懂一门生意，再沿着关系和出处继续研究。**

星图保留了市场关系可视化、公司知识阅读和原文展开的实现，适合学习产品设计、研究信息结构，或作为你自己的知识工具的代码参考。

- **想学习公司与行业：** 看演示，了解“关系 → 生意 → 出处”的阅读方式。
- **想做知识产品或二次开发：** 查看 React / TypeScript / Three.js 的页面与图谱实现。
- **想把星图用于自己的场景：** 留下你要解决的问题，一起讨论可行的实现。

## 选一个入口，继续探索

| 我现在想做什么 | 从这里开始 |
| --- | --- |
| 看源码、了解架构 | [进入 app/](app/) · [开发与运行说明](docs/development-guide.md) |
| 提一个使用场景或改进建议 | [填写场景反馈](https://github.com/ZHY999999999/jiangzao-xingtu-open-source/issues/new?template=use-case.yml) |
| 报告问题、交流实现 | [查看 Issues](https://github.com/ZHY999999999/jiangzao-xingtu-open-source/issues) · [参与贡献](CONTRIBUTING.md) |
| 关注后续作品 | [关注作者 GitHub](https://github.com/ZHY999999999)；觉得有用也欢迎 Star 收藏 |

**我们更想听到具体问题。** 例如：“我在学一个行业，最难的是找到上下游关系”，或“我想把这套界面用在自己的行业知识库”。无需留下手机号、微信或其他私人信息。

## 本地运行与内容边界

完整构建需要 **Node.js 22、Python 3.11+ 与单独保存的运行数据包**。本仓库不提供该数据包的公开下载，也不承诺可以通过反馈索取。准备好有权使用、并与清单匹配的数据后，再按[开发与数据恢复说明](docs/development-guide.md)运行。

不准备运行数据也可以先阅读：

- [页面与组件源码](app/src/)
- [已收录的公司生意概览](app/content/company-overview/)
- [内容构建边界](docs/unified-content-build.md)

当前源码版本为 **1.2.26**。目录覆盖、已收录的生意概览与深度解读是不同层次，不能把公司目录数量理解为所有公司均已完成研究。历史资料保留各自记录日期，不能当作今天的市场事实；项目不提供投资建议或收益承诺。

## 许可与致谢

自主代码采用 [MIT License](LICENSE)。第三方依赖、字体、图片、引用原文及数据遵循各自许可和权利；MIT 不为第三方材料提供额外授权。原私有项目历史、凭据与私人研究资料不在此公开仓库中。

---

<p align="center"><strong>从一个点出发，把理解连成图。</strong><br><sub>降噪星图 · 保持好奇，继续探索。</sub></p>
