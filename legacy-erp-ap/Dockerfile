# 多阶段构建：
#   1) 用 python 从 boapi-spec 生成工具 manifest（规格即工具，构建期强制同步）
#   2) Maven 构建（容器内构建，宿主机无需 JDK）
#   3) JRE 运行
FROM python:3.12-slim AS manifest
WORKDIR /workspace
RUN pip install --no-cache-dir pyyaml==6.0.2
COPY boapi-spec/bo-ap.yaml boapi-spec/bo-ap.yaml
COPY scripts/gen_manifest.py scripts/gen_manifest.py
RUN python scripts/gen_manifest.py --out /workspace/out/bo-tools-manifest.json

FROM maven:3.9-eclipse-temurin-21 AS build
WORKDIR /workspace
COPY legacy-erp-ap/pom.xml legacy-erp-ap/pom.xml
COPY --from=manifest /workspace/out/bo-tools-manifest.json legacy-erp-ap/src/main/resources/bo-tools-manifest.json
COPY legacy-erp-ap/src legacy-erp-ap/src
RUN mvn -f legacy-erp-ap/pom.xml -q -DskipTests package

FROM eclipse-temurin:21-jre
WORKDIR /app
COPY --from=build /workspace/legacy-erp-ap/target/legacy-erp-ap-1.0.0.jar app.jar
ENV TZ=Asia/Shanghai
EXPOSE 8080
ENTRYPOINT ["java", "-jar", "/app/app.jar"]
