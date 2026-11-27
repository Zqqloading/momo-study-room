# 前端第三方库（随仓库分发）

离线可用，不走 CDN。与 `web/index.html` 的 importmap 一一对应。

| 路径 | 包 | 版本 | 许可证 |
|---|---|---|---|
| `three/three.module.js` | [three](https://github.com/mrdoob/three.js) | 0.160.0 | MIT |
| `three/addons/loaders/GLTFLoader.js` | three examples/jsm | 0.160.0 | MIT |
| `three/addons/utils/BufferGeometryUtils.js` | three examples/jsm | 0.160.0 | MIT |
| `three-vrm/three-vrm.module.js` | [@pixiv/three-vrm](https://github.com/pixiv/three-vrm) | 2.1.2 | MIT |

只 vendored `GLTFLoader` 的依赖闭包（`BufferGeometryUtils`）与 three-vrm 的打包产物；
升级三个文件时要一起换版本号，并同步本表。
