# MinIO 容器化部署文档

## 1. 目标

本文说明如何使用 Docker / Docker Compose 部署知识库项目依赖的 MinIO 对象存储服务。

MinIO 用于保存知识库接入流程中的原始文档、解析中间文件或后续生成的附件资源。

适用范围：

- 本地开发环境。
- 测试环境。
- 单节点 MVP 部署。

生产环境可以继续使用本文的部署方式，但应补充 HTTPS、访问密钥管理、桶权限隔离、备份、监控和容量规划。

## 2. 技术基线

| 项 | 选择 |
|---|---|
| 对象存储 | MinIO |
| 容器镜像 | `minio/minio:RELEASE.2025-09-07T16-13-09Z` |
| API 端口 | `9000` |
| Console 端口 | `9001` |
| 数据目录 | Docker volume |
| 默认 bucket | `knowledge-base` |

说明：

- `9000`：S3 API 访问端口，应用程序使用该端口上传和下载文件。
- `9001`：MinIO Console 管理后台端口，浏览器访问该端口进行管理。
- 镜像标签不要使用 `latest`，避免环境不可重复。
- 如果 `minio/minio:latest` 可以拉取，可以通过 `docker run --rm minio/minio:latest --version` 查看它对应的固定版本。

## 3. 目录建议

```text
project-root/
├── docker-compose.yml
└── docs/
    └── MinIO容器化部署.md
```

MinIO 数据不应写入项目源码目录，应使用 Docker volume 或独立挂载盘。

## 4. Docker Compose 配置

项目根目录的 `docker-compose.yml` 中增加 MinIO 服务：

```yaml
services:
  minio:
    image: minio/minio:RELEASE.2025-09-07T16-13-09Z
    command: server /data --console-address ":9001"
    environment:
      MINIO_ROOT_USER: linburgh
      MINIO_ROOT_PASSWORD: linburgh
    ports:
      - "9000:9000"
      - "9001:9001"
    volumes:
      - minio_data:/data
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:9000/minio/health/live"]
      interval: 10s
      timeout: 5s
      retries: 5

volumes:
  minio_data:
```

说明：

- `MINIO_ROOT_USER`：MinIO 管理员账号。
- `MINIO_ROOT_PASSWORD`：MinIO 管理员密码，本地开发可用简单密码，生产必须改为强密码并通过环境变量或密钥系统注入。
- `minio_data`：持久化对象数据。
- `healthcheck`：用于 Compose 或部署平台判断 MinIO 是否可用。

如果 `docker-compose.yml` 已有 PostgreSQL 服务，只需要把 `minio` 服务和 `minio_data` volume 合并进去。

## 5. 本地启动

在项目根目录执行：

```bash
docker compose up -d minio
```

查看状态：

```bash
docker compose ps minio
```

查看日志：

```bash
docker compose logs -f minio
```

停止服务：

```bash
docker compose stop minio
```

停止并删除容器，但保留数据卷：

```bash
docker compose down
```

删除数据卷会清空对象数据，谨慎执行：

```bash
docker compose down -v
```

## 6. 访问 Console

浏览器访问：

```text
http://127.0.0.1:9001
```

登录账号：

```text
用户名：linburgh
密码：linburgh
```

登录后创建 bucket：

```text
knowledge-base
```

本地开发阶段可以保持 bucket 为 private，由应用通过 access key 访问。

## 7. 使用 mc 初始化 bucket

如果希望通过命令初始化 bucket，可以临时使用 MinIO Client 容器执行：

```bash
docker run --rm --network knowledge-base_default \
  minio/mc:RELEASE.2025-07-21T05-28-08Z \
  sh -c "mc alias set local http://minio:9000 linburgh linburgh && mc mb --ignore-existing local/knowledge-base"
```

说明：

- `knowledge-base_default` 是 Docker Compose 默认网络名，实际名称通常为 `<项目目录名>_default`。
- 如果项目目录名不是 `knowledge-base`，先执行 `docker network ls` 确认网络名。
- `mc mb --ignore-existing` 会在 bucket 已存在时忽略错误。

如果在宿主机安装了 `mc`，也可以执行：

```bash
mc alias set local http://127.0.0.1:9000 linburgh linburgh
mc mb --ignore-existing local/knowledge-base
```

## 8. 应用配置示例

项目配置可以增加对象存储相关配置：

```yaml
default:
  object_storage_endpoint: http://127.0.0.1:9000
  object_storage_access_key: linburgh
  object_storage_secret_key: linburgh
  object_storage_bucket: knowledge-base
  object_storage_secure: false
```

如果应用运行在 Docker Compose 网络内部，endpoint 应改为服务名：

```yaml
default:
  object_storage_endpoint: http://minio:9000
```

说明：

- 宿主机运行应用：使用 `http://127.0.0.1:9000`。
- 容器内运行应用：使用 `http://minio:9000`。
- 生产环境应使用 HTTPS，并将 `object_storage_secure` 设置为 `true`。

## 9. 验证上传和下载

使用 `mc` 上传测试文件：

```bash
echo "hello minio" > /tmp/minio-test.txt
mc cp /tmp/minio-test.txt local/knowledge-base/minio-test.txt
```

查看对象：

```bash
mc ls local/knowledge-base
```

下载验证：

```bash
mc cp local/knowledge-base/minio-test.txt /tmp/minio-test-download.txt
cat /tmp/minio-test-download.txt
```

删除测试对象：

```bash
mc rm local/knowledge-base/minio-test.txt
```

## 10. 备份和恢复

### 10.1 备份

使用 Docker volume 时，可以将对象数据同步到备份目录：

```bash
mkdir -p backups/minio

docker run --rm \
  -v knowledge-base_minio_data:/data:ro \
  -v "$(pwd)/backups/minio:/backup" \
  alpine \
  sh -c "cd /data && tar czf /backup/minio_data_$(date +%Y%m%d%H%M%S).tar.gz ."
```

说明：

- `knowledge-base_minio_data` 是 Compose 创建的 volume 名，实际名称通常为 `<项目目录名>_minio_data`。
- 备份前应确认没有大量写入任务正在执行。

### 10.2 恢复

恢复会覆盖目标数据，执行前确认目标环境可以被覆盖。

```bash
docker compose stop minio

docker run --rm \
  -v knowledge-base_minio_data:/data \
  -v "$(pwd)/backups/minio:/backup" \
  alpine \
  sh -c "rm -rf /data/* && tar xzf /backup/minio_data_xxx.tar.gz -C /data"

docker compose up -d minio
```

生产环境建议使用 MinIO 官方复制、版本控制、生命周期和对象锁能力，而不是只依赖 volume 级备份。

## 11. 生产配置建议

生产环境至少调整以下项：

- 使用强密码，不提交到 Git。
- 不直接暴露 `9000`、`9001` 到公网。
- 使用 HTTPS 或放在可信反向代理后。
- 应用账号和管理账号分离，应用账号只授予必要 bucket 权限。
- 将对象数据卷挂载到可靠磁盘。
- 配置容量、水位、请求量、错误率和磁盘 IO 监控。
- 配置对象备份、跨节点复制或跨区域复制。
- 按文档大小、并发上传量和保留周期规划磁盘容量。
- 不使用 `latest` 镜像标签。
- 升级 MinIO 前先在测试环境验证上传、下载、权限和已有对象兼容性。

## 12. 常见问题

### 12.1 端口被占用

检查端口：

```bash
ss -ltnp | grep -E '9000|9001'
```

如果端口冲突，可以修改 Compose 端口映射：

```yaml
ports:
  - "19000:9000"
  - "19001:9001"
```

应用 endpoint 同步改为：

```text
http://127.0.0.1:19000
```

Console 地址同步改为：

```text
http://127.0.0.1:19001
```

### 12.2 Console 可以登录，但应用无法连接

检查：

- 应用使用的是 API 端口 `9000`，不是 Console 端口 `9001`。
- `object_storage_endpoint` 是否与应用运行位置匹配。
- bucket 是否已经创建。
- access key 和 secret key 是否正确。
- 容器内应用是否能解析 `minio` 服务名。

### 12.3 mc 初始化失败

检查 Compose 网络名：

```bash
docker network ls
```

如果网络名不是 `knowledge-base_default`，把命令中的网络名替换为实际名称。

### 12.4 健康检查失败

检查容器日志：

```bash
docker compose logs minio
```

确认 `command` 包含：

```text
server /data --console-address ":9001"
```

并确认 `MINIO_ROOT_USER`、`MINIO_ROOT_PASSWORD` 均已设置。

### 12.5 拉取镜像时访问 quay.io 失败

如果出现类似错误：

```text
Get "https://quay.io/v2/": read: connection reset by peer
```

说明 Docker 在拉取 MinIO 镜像时访问 `quay.io` 失败。可以把镜像地址改成代理地址：

```yaml
services:
  minio:
    image: minio/minio:RELEASE.2025-09-07T16-13-09Z
```

然后重新启动：

```bash
docker compose pull minio
docker compose up -d minio
```

如果 Docker Hub 不可用，可以换成官方 Quay 地址后在网络环境可访问 `quay.io` 的机器上拉取：

```yaml
services:
  minio:
    image: quay.io/minio/minio:RELEASE.2025-09-07T16-13-09Z
```
