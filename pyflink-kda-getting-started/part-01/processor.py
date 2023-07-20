import os
import json

from pyflink.table import EnvironmentSettings, TableEnvironment

IS_LOCAL_KAFKA = os.environ.get("IS_LOCAL_KAFKA") is not None
IS_LOCAL_FLINK = os.environ.get("IS_LOCAL_FLINK") is not None
FLINK_VERSION = os.environ.get("FLINK_VERSION", "1.15.2")

env_settings = EnvironmentSettings.in_streaming_mode()
table_env = TableEnvironment.create(env_settings)

APPLICATION_PROPERTIES_FILE_PATH = "/etc/flink/application_properties.json"  # on kda
if IS_LOCAL_KAFKA:
    APPLICATION_PROPERTIES_FILE_PATH = "application_properties.json"  # local
    # on local, multiple jar files can be passed after being delimited by a semicolon
    CURRENT_DIR = os.path.dirname(os.path.realpath(__file__))
    FLINK_SQL_CONNECTOR_KAFKA = f"flink-sql-connector-kafka-{FLINK_VERSION}.jar"
    table_env.get_config().set(
        "pipeline.jars", f"file://{os.path.join(CURRENT_DIR, 'lib', FLINK_SQL_CONNECTOR_KAFKA)}"
    )


def get_application_properties():
    if os.path.isfile(APPLICATION_PROPERTIES_FILE_PATH):
        with open(APPLICATION_PROPERTIES_FILE_PATH, "r") as file:
            contents = file.read()
            properties = json.loads(contents)
            return properties
    else:
        print(f"A file at '{APPLICATION_PROPERTIES_FILE_PATH}' was not found")


def property_map(props: dict, property_group_id: str):
    for prop in props:
        if prop["PropertyGroupId"] == property_group_id:
            return prop["PropertyMap"]


def create_source_table(
    table_name: str, topic_name: str, bootstrap_servers: str, startup_mode: str
):
    return f"""
    CREATE TABLE {table_name} (
        event_time TIMESTAMP(3),
        ticker VARCHAR(6),
        price DOUBLE
    )
    WITH (
        'connector' = 'kafka',
        'topic' = '{topic_name}',
        'properties.bootstrap.servers' = '{bootstrap_servers}',
        'properties.group.id' = 'source-group',
        'format' = 'json',
        'scan.startup.mode' = '{startup_mode}'
    )
    """


def create_sink_table(table_name: str, topic_name: str, bootstrap_servers: str):
    return f"""
    CREATE TABLE {table_name} (
        event_time TIMESTAMP(3),
        ticker VARCHAR(6),
        price DOUBLE
    )
    WITH (
        'connector' = 'kafka',
        'topic' = '{topic_name}',
        'properties.bootstrap.servers' = '{bootstrap_servers}',        
        'format' = 'json',
        'key.format' = 'json',
        'key.fields' = 'ticker',
        'sink.partitioner' = 'fixed'
    )
    """


def create_print_table(table_name: str):
    return f"""
    CREATE TABLE {table_name} (
        event_time TIMESTAMP(3),
        ticker VARCHAR(6),
        price DOUBLE
    )
    WITH (
        'connector' = 'print'
    )
    """


def main():
    ## map consumer/producer properties
    props = get_application_properties()
    # consumer
    consumer_property_group_key = "consumer.config.0"
    consumer_properties = property_map(props, consumer_property_group_key)
    consumer_table_name = consumer_properties["table.name"]
    consumer_topic_name = consumer_properties["topic.name"]
    consumer_bootstrap_servers = consumer_properties["bootstrap.servers"]
    consumer_startup_mode = consumer_properties["startup.mode"]
    # producer
    producer_property_group_key = "producer.config.0"
    producer_properties = property_map(props, producer_property_group_key)
    producer_table_name = producer_properties["table.name"]
    producer_topic_name = producer_properties["topic.name"]
    producer_bootstrap_servers = producer_properties["bootstrap.servers"]
    # print
    print_table_name = "sink_print"
    ## create a souce table
    table_env.execute_sql(
        create_source_table(
            consumer_table_name,
            consumer_topic_name,
            consumer_bootstrap_servers,
            consumer_startup_mode,
        )
    )
    ## create sink tables
    table_env.execute_sql(
        create_sink_table(producer_table_name, producer_topic_name, producer_bootstrap_servers)
    )
    table_env.execute_sql(create_print_table("sink_print"))
    ## insert into sink tables
    if IS_LOCAL_FLINK:
        source_table = table_env.from_path(consumer_table_name)
        statement_set = table_env.create_statement_set()
        statement_set.add_insert(producer_table_name, source_table)
        statement_set.add_insert(print_table_name, source_table)
        statement_set.execute().wait()
    else:
        table_result = table_env.execute_sql(
            f"INSERT INTO {producer_table_name} SELECT * FROM {consumer_table_name}"
        )
        print(table_result.get_job_client().get_job_status())


if __name__ == "__main__":
    main()
