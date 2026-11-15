# 合约编译状态

- 状态：**已编译通过**（2026-11-16）。
- 编译器：solc 0.8.28+commit.7893614a（经 npm 包 `solc` 的 solcjs 运行；本机无原生 solc/forge，故用 npx 方式）。
- 命令：`npx -y solc@0.8.28 --bin --abi --optimize -o out CommitRegistry.sol FollowRegistry.sol`
- 结果：exit 0，无错误、无警告。产物在 `out/`（已 gitignore，不入库）：
  - `CommitRegistry`：bytecode 1717 bytes（hex 3434 字符），ABI 已生成。
  - `FollowRegistry`：bytecode 993 bytes（hex 1986 字符），ABI 已生成。
- 部署状态：**未部署到任何网络**（按硬停条款，部署是后续单独批准的步骤）。
- 审计状态：未审计，骨架代码，不得直接用于主网资金相关场景（两合约本身不持有资金）。
