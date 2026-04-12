import unittest
import datetime
from sdge_usage import get_time_periods, get_charging_recommendation

date_format = "%m/%d/%Y"

class UnitTest(unittest.TestCase):
    def test_1(self):
        date_string = "04/06/2023"
        time_string = "03:40 PM"
        datetime_object = datetime.datetime.strptime(date_string, date_format)
        time_obj = datetime.datetime.strptime(time_string, '%I:%M %p').time()
        self.assertEqual(get_time_periods(datetime_object, time_obj), "Off Peak")

    def test_2(self):
        date_string = "04/06/2023"
        time_string = "10:40 AM"
        datetime_object = datetime.datetime.strptime(date_string, date_format)
        time_obj = datetime.datetime.strptime(time_string, '%I:%M %p').time()
        self.assertEqual(get_time_periods(datetime_object, time_obj), "Super Off Peak")

    def test_3(self):
        date_string = "04/06/2023"
        time_string = "8:40 PM"
        datetime_object = datetime.datetime.strptime(date_string, date_format)
        time_obj = datetime.datetime.strptime(time_string, '%I:%M %p').time()
        self.assertEqual(get_time_periods(datetime_object, time_obj), "On Peak")

    def test_4(self):   # holiday super off peak
        date_string = "07/04/2023"
        time_string = "08:40 AM"
        datetime_object = datetime.datetime.strptime(date_string, date_format)
        time_obj = datetime.datetime.strptime(time_string, '%I:%M %p').time()
        self.assertEqual(get_time_periods(datetime_object, time_obj), "Super Off Peak")

    def test_5(self):   # weenend super off peak
        date_string = "04/08/2023"
        time_string = "08:40 AM"
        datetime_object = datetime.datetime.strptime(date_string, date_format)
        time_obj = datetime.datetime.strptime(time_string, '%I:%M %p').time()
        self.assertEqual(get_time_periods(datetime_object, time_obj), "Super Off Peak")

class TestChargingRecommendation(unittest.TestCase):
    def test_super_off_peak_surplus(self):
        result = {"super_off_peak_kwh": -142.3, "off_peak_kwh": 10.0}
        rec = get_charging_recommendation(result)
        self.assertEqual(rec["recommended_period"], "Super Off-Peak")
        self.assertEqual(rec["charge_start"], 0)
        self.assertEqual(rec["charge_end"], 6)
        self.assertGreater(rec["surplus_kwh"], 0)

    def test_off_peak_surplus_when_sop_positive(self):
        result = {"super_off_peak_kwh": 10.0, "off_peak_kwh": -38.1}
        rec = get_charging_recommendation(result)
        self.assertEqual(rec["recommended_period"], "Off-Peak")
        self.assertEqual(rec["charge_start"], 21)
        self.assertEqual(rec["charge_end"], 24)
        self.assertGreater(rec["surplus_kwh"], 0)

    def test_no_surplus_defaults_to_super_off_peak(self):
        result = {"super_off_peak_kwh": 50.0, "off_peak_kwh": 30.0}
        rec = get_charging_recommendation(result)
        self.assertEqual(rec["recommended_period"], "Super Off-Peak")
        self.assertEqual(rec["surplus_kwh"], 0.0)


if __name__ == '__main__':
    unittest.main()
