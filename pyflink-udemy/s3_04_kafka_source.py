import os

from pyflink.table import EnvironmentSettings, TableEnvironment

BOOTSTRAP_SERVERS = os.getenv("BOOTSTRAP_SERVERS", "localhost:9093")
# https://nightlies.apache.org/flink/flink-docs-release-1.16/docs/connectors/table/kafka/
FLINK_SQL_CONNECTOR_KAFKA = "flink-sql-connector-kafka-1.16.0.jar"

env_settings = EnvironmentSettings.in_streaming_mode()
table_env = TableEnvironment.create(env_settings)
# https://nightlies.apache.org/flink/flink-docs-release-1.16/docs/dev/python/dependency_management/
kafka_jar = os.path.join(os.path.abspath(os.path.dirname(__file__)), FLINK_SQL_CONNECTOR_KAFKA)
table_env.get_config().set("pipeline.jars", f"file://{kafka_jar}")

## create kafka source table
table_env.execute_sql(
    f"""
    CREATE TABLE product_sales (
        `seller_id` VARCHAR,
        `product` VARCHAR,
        `quantity` INT,
        `product_price` DOUBLE,
        `sales_date` VARCHAR
    ) WITH (
        'connector' = 'kafka',
        'topic' = 'product_sales',
        'properties.bootstrap.servers' = '{BOOTSTRAP_SERVERS}',
        'properties.group.id' = 'source-demo',
        'format' = 'json',
        'scan.startup.mode' = 'earliest-offset',
        'json.fail-on-missing-field' = 'false',
        'json.ignore-parse-errors' = 'true'
    )
    """
)

## create print sink table
table_env.execute_sql(
    f"""
    CREATE TABLE print (
        `seller_id` VARCHAR,
        `product` VARCHAR,
        `quantity` INT,
        `product_price` DOUBLE,
        `sales_date` VARCHAR
    ) WITH (
        'connector' = 'print'
    )
    """
)

## insert into sink table
tbl = table_env.from_path("product_sales")
tbl.execute_insert("print").wait()
