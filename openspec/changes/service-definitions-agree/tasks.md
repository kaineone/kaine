## 1. Alignment
- [x] 1.1 Pin Qdrant `v1.19.1` in `compose/kaine.yml` and `quadlet/kaine-qdrant.container`, and in the deployment doc; the distributed-deployment spec names the pinned image rather than a version. `v1.19.1`, like `v1.18.0`, ships bash and neither curl nor wget, so the `/dev/tcp` health probe is unchanged.

## 2. Test
- [x] 2.1 `tests/test_service_definitions_agree.py`: images, native Qdrant version, ports, and the Redis and llama-server arguments agree across every definition. Changing one Qdrant pin or one Redis flag fails it.
