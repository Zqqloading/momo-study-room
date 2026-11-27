# 3D 形象放这里

1. 用 [VRoid Studio](https://vroid.com/studio) 免费捏一个角色，导出为 `.vrm`。
2. 或者从 VRoid Hub / Booth 下载允许使用的免费 VRM 模型。
3. 把文件命名为 `avatar.vrm`，放在这个目录：`assets/avatar.vrm`。
4. 刷新页面，会自动换成 3D 形象；没有这个文件时页面用占位形象。

口型目前是**幅度驱动**：按 TTS 音频的响度控制 `aa` 表情，嘴会随声音开合，但不是音素级对位。

## 当前模型

- **Sendagaya Shino**（千駄ヶ谷 篠），VRoid beta 样例，VRM 0.x。
- 许可证：CC0（模型内嵌 `licenseName: CC0`，`allowedUser: Everyone`，商业使用允许）。
- 来源：`https://github.com/madjin/vrm-samples/tree/master/vroid/beta/Sendagaya_Shino.vrm`
- 表情：`a/i/u/e/o/blink/blink_l/blink_r/angry/fun/joy/sorrow`；three-vrm 会把 VRM0 的 `a` 映射为 `aa`。
- 文件约 15MB，54 根人形骨骼，17 组 spring bone；不需要署名。

站姿与手指参数按 Shino 的 VRoid 归一化骨骼调；换其他 VRM 后，如果手臂或手指方向不对，调 `web/app.js` 的 `poseVrm()` 与 `poseFingers()`。

注意：VRoid Hub 上标“CC0”的模型不一定真的用 CC0；以模型内嵌的许可证元数据为准。
VRoid Studio 的 **AvatarSample A/B/C 不是 CC0**，有单独的使用条件，不要当作公有领域素材。

