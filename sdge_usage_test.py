import unittest
import datetime
from sdge_usage import get_time_periods 

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

if __name__ == '__main__':
    unittest.main()
