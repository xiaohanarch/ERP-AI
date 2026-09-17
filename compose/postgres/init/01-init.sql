-- PostgreSQL 初始化：一次实例三个数据库（存量 ERP / AI 网关 / Hub 检查点）
-- erp 由 POSTGRES_DB 预建；此处补建 ai_gw 与 hub。
-- 显式 UTF8 编码，避免 Windows 下 init 脚本编码漂移
CREATE DATABASE ai_gw WITH ENCODING 'UTF8' LC_COLLATE 'C' LC_CTYPE 'C' TEMPLATE template0;
CREATE DATABASE hub WITH ENCODING 'UTF8' LC_COLLATE 'C' LC_CTYPE 'C' TEMPLATE template0;
