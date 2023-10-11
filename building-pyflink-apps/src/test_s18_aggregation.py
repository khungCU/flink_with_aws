import datetime
import typing
import time
import pytest

from pyflink.common import WatermarkStrategy
from pyflink.common.watermark_strategy import TimestampAssigner
from pyflink.datastream import StreamExecutionEnvironment

from models import UserStatistics
from helpers import build_flight, build_user_statistics
from s18_aggregation import define_workflow


@pytest.fixture(scope="module")
def env():
    env = StreamExecutionEnvironment.get_execution_environment()
    yield env


@pytest.fixture(scope="module")
def default_watermark_strategy():
    class DefaultTimestampAssigner(TimestampAssigner):
        def extract_timestamp(self, value, record_timestamp):
            return int(time.time_ns() / 1000000)

    return WatermarkStrategy.for_monotonous_timestamps().with_timestamp_assigner(
        DefaultTimestampAssigner()
    )


def test_user_statistics_should_create_statistics_using_flight_data():
    flight = build_flight()
    stats = UserStatistics.from_flight(flight)

    expected_duration = int(
        (
            datetime.datetime.fromisoformat(flight.arrival_time)
            - datetime.datetime.fromisoformat(flight.departure_time)
        ).seconds
        / 60
    )

    assert flight.email_address == stats.email_address
    assert expected_duration == stats.total_flight_duration
    assert 1 == stats.number_of_flights


def test_user_statistics_should_merge_two_user_statistics():
    stats1 = build_user_statistics()
    stats2 = build_user_statistics(email_address=stats1.email_address)

    merged = UserStatistics.merge(stats1, stats2)

    assert stats1.email_address == merged.email_address
    assert (
        stats1.total_flight_duration + stats2.total_flight_duration
    ) == merged.total_flight_duration
    assert 2 == merged.number_of_flights


def test_user_statistics_should_fail_for_different_email_address():
    stats1 = build_user_statistics()
    stats2 = build_user_statistics(email_address="different@email.address")

    assert stats1.email_address != stats2.email_address
    with pytest.raises(AssertionError):
        UserStatistics.merge(stats1, stats2)


def test_define_workflow_should_convert_flight_data_to_user_statistics(
    env, default_watermark_strategy
):
    flight_data = build_flight()
    flight_stream = env.from_collection(
        collection=[flight_data.to_row()]
    ).assign_timestamps_and_watermarks(default_watermark_strategy)

    elements: typing.List[UserStatistics] = list(
        define_workflow(flight_stream).execute_and_collect()
    )
    expected = UserStatistics.from_flight(flight_data)

    assert expected.email_address == next(iter(elements)).email_address
    assert expected.total_flight_duration == next(iter(elements)).total_flight_duration
    assert expected.number_of_flights == next(iter(elements)).number_of_flights


def test_define_workflow_should_group_statistics_by_email_address(env, default_watermark_strategy):
    flight_data_1 = build_flight()
    flight_data_2 = build_flight()
    flight_data_3 = build_flight()
    flight_data_3.email_address = flight_data_1.email_address

    flight_stream = env.from_collection(
        collection=[flight_data_1.to_row(), flight_data_2.to_row(), flight_data_3.to_row()]
    ).assign_timestamps_and_watermarks(default_watermark_strategy)

    elements: typing.List[UserStatistics] = list(
        define_workflow(flight_stream).execute_and_collect()
    )

    stats_1 = UserStatistics.from_flight(flight_data_1)
    stats_2 = UserStatistics.from_flight(flight_data_2)
    stats_3 = UserStatistics.from_flight(flight_data_3)

    assert len(elements) == 2
    for e in elements:
        if e.email_address == flight_data_1.email_address:
            assert (
                e.total_flight_duration
                == UserStatistics.merge(stats_1, stats_3).total_flight_duration
            )
            assert e.number_of_flights == UserStatistics.merge(stats_1, stats_3).number_of_flights
        else:
            assert e.total_flight_duration == stats_2.total_flight_duration
            assert e.number_of_flights == stats_2.number_of_flights


def test_define_workflow_should_window_statistics_by_minute(env):
    flight_data_1 = build_flight()
    flight_data_2 = build_flight()
    flight_data_2.email_address = flight_data_1.email_address
    flight_data_3 = build_flight()
    flight_data_3.email_address = flight_data_1.email_address
    flight_data_3.departure_airport_code = "LATE"

    class CustomTimestampAssigner(TimestampAssigner):
        def extract_timestamp(self, value, record_timestamp):
            if value.departure_airport_code == "LATE":
                # higher than 27300 makes a separate window
                # shouldn't it be values lower than 60000???
                return int(time.time_ns() / 1000000) + 60000
            else:
                return int(time.time_ns() / 1000000)

    custom_watermark_strategy = (
        WatermarkStrategy.for_monotonous_timestamps().with_timestamp_assigner(
            CustomTimestampAssigner()
        )
    )

    flight_stream = env.from_collection(
        collection=[flight_data_1.to_row(), flight_data_2.to_row(), flight_data_3.to_row()]
    ).assign_timestamps_and_watermarks(custom_watermark_strategy)

    elements: typing.List[UserStatistics] = list(
        define_workflow(flight_stream).execute_and_collect()
    )
    stats_1 = UserStatistics.from_flight(flight_data_1)
    stats_2 = UserStatistics.from_flight(flight_data_2)
    stats_3 = UserStatistics.from_flight(flight_data_3)

    assert len(elements) == 2
    for e in elements:
        if e.number_of_flights > 1:
            assert (
                e.total_flight_duration
                == UserStatistics.merge(stats_1, stats_2).total_flight_duration
            )
        else:
            assert e.total_flight_duration == stats_3.total_flight_duration
