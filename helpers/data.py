from bs4 import BeautifulSoup
import random
import re
import requests
import constants as c
from datetime import date, datetime
from dateutil.relativedelta import relativedelta


class LittleSpider(object):
    def __init__(self, username=c.BILL_USERNAME, password=c.BILL_PASSWORD, domain=c.BILL_DOMAIN):
        self.username = username
        self.password = password
        self.domain = domain
        self.name = None
        self.bill_id = None
        self.money = None

        self.session = requests.Session()
        adapter = requests.adapters.HTTPAdapter(max_retries=c.MAX_HTTP_RETRIES)
        self.session.mount('https://', adapter)

    def login(self):
        login_form_url = '%s/index.php?act_id=access' % self.domain

        self.session.get(self.domain)
        r = self.session.post(login_form_url,
                              data={'login': self.username,
                                    'password': self.password})
        assert r.status_code == 200

        self.parse_user_data(r.content)

    def parse_user_data(self, response):
        data = BeautifulSoup(response, 'html5lib').find_all('dd')

        self.money = float(data[3].find('b').text.split()[0])  # how rich we are?
        # (may fail with overflow for Comp&Copy accounts)
        self.name = data[4].text.lstrip()
        self.bill_id = data[5].text.lstrip()

    def get_logs(self,
                 months=c.MAX_MONTHS,
                 randomize_day=False,
                 hide_ip=False,
                 hide_time=False,
                 hide_date=False,
                 hide_duration=False,
                 hide_sent=False,
                 hide_received=False,
                 hide_plan=False,
                 hide_server=False,
                 round_duration=False,
                 round_sent=False,
                 round_received=False,
                 aggressive_round=False,
                 keep_default=False):
        # default privacy settings (not secure if шеванайкраща)
        # recommended privacy settings: F, T, T, F, F, T, T, T, F, T, T, T, T
        # make sure to use with foil, otherwise they'll finsldflgkfgfsfyfdysdygfgsd
        if not all((randomize_day, hide_ip, hide_time, hide_date, hide_duration, hide_sent, hide_received, hide_plan,
                    hide_server, round_duration, round_sent, round_received, aggressive_round)) and not keep_default:
            raise ValueError('You should review LittleSpider.get_logs params to continue...')
        if not self.name:
            self.login()
        to_date = date.today()
        if randomize_day:
            to_date = to_date.replace(day=random.randint(1, to_date.day))
        else:
            to_date = to_date.replace(day=1)
        from_date = to_date - relativedelta(months=months)
        return self.get_logs_for_interval(from_date,
                                          to_date,
                                          hide_ip,
                                          hide_time,
                                          hide_date,
                                          hide_duration,
                                          hide_sent,
                                          hide_received,
                                          hide_plan,
                                          hide_server,
                                          round_duration,
                                          round_sent,
                                          round_received,
                                          aggressive_round)

    def get_logs_for_interval(self, from_date, to_date, *args, **kwargs):
        stats_form_url = '%s/index.php?act_id=view_stats' % self.domain

        fmt = '%Y-%m-%d'
        from_date, to_date = from_date.strftime(fmt), to_date.strftime(fmt)

        self.session.get(stats_form_url)
        r = self.session.post(stats_form_url,
                              data={'from_date': from_date,
                                    'to_date': to_date})
        assert r.status_code == 200
        # here you may want to disable internet for extra security

        return LittleSpider.parse_logs(r.content, *args, **kwargs)

    @staticmethod
    def parse_logs(response,
                   hide_ip,
                   hide_time,
                   hide_date,
                   hide_duration,
                   hide_sent,
                   hide_received,
                   hide_plan,
                   hide_server,
                   round_duration,
                   round_sent,
                   round_received,
                   aggressive_round):
        data = BeautifulSoup(response, 'html5lib').find('tbody').find_all('tr')

        res = []
        time_parser = TimeParser(hide_time, hide_date)
        duration_parser = DurationParser(round_duration, aggressive_round)
        bytes_parser = BytesParser(round_sent, round_received, aggressive_round)
        for row in data:
            row = row.find_all('td')
            start, duration, plan, received, sent, local_ip, ip, server = \
                [(x.find('nobr') or x).text.strip() for x in row]

            res.append({'start': time_parser.parse(start),
                        'duration': None if hide_duration else duration_parser.parse(duration),
                        'plan': None if hide_plan else plan,
                        'sent': None if hide_sent else bytes_parser.parse_sent(sent),
                        'received': None if hide_received else bytes_parser.parse_received(received),
                        'local_ip': None if hide_ip else local_ip,
                        'ip': None if hide_ip else ip,
                        'server': None if hide_server else server})
        return res


class BytesParser(object):
    multipliers = 'bKMGT'

    def __init__(self, round_sent, round_received, aggressive_round):
        self.round_sent = round_sent
        self.round_received = round_received
        self.aggressive_round = aggressive_round

    def parse_sent(self, data):
        num, multiplier = BytesParser.parse_bytes(data)
        if self.round_sent:
            num = self.round(num)
        return num, multiplier

    def parse_received(self, data):
        num, multiplier = BytesParser.parse_bytes(data)
        if self.round_received:
            num = self.round(num)
        return num, multiplier

    def round(self, num):
        if self.aggressive_round:
            return 1
        i = 0
        while num > 10:
            num /= 10
            i += 1
        return round(num) * (10 ** i)

    @staticmethod
    def parse_bytes(data):
        num, multiplier = data.split()
        num, multiplier = float(num), BytesParser.multipliers.index(multiplier[0])
        return num, multiplier


class DurationParser(object):
    def __init__(self, round_duration, aggressive_round):
        self.round_duration = round_duration
        self.aggressive_round = aggressive_round

    def parse(self, data):
        return DurationParser.parse_duration(data, self.round_duration, self.aggressive_round)

    @staticmethod
    def parse_duration(data, round_duration=False, aggressive_round=False):
        # bad code section, sorry for my regexp
        days = int('день' in data)
        hours = re.match('(?:.+ |)(\d+) годин', data)
        hours = int(hours.groups()[0]) if hours else 0
        minutes = re.match('(?:.+ |)(\d+) хвилин', data)
        minutes = int(minutes.groups()[0]) if minutes else 0
        seconds = re.match('(?:.+ |)(\d+) секунд', data)
        seconds = int(seconds.groups()[0]) if seconds else 0

        if round_duration:
            if days:
                if aggressive_round:
                    days = 1
                hours = minutes = seconds = 0
            elif hours:
                if aggressive_round:
                    hours = 1
                minutes = seconds = 0
            elif minutes:
                if aggressive_round:
                    minutes = 1 if minutes == 1 else 30
                else:
                    minutes = (minutes // 10 + bool(minutes % 10)) * 10
                seconds = 0
            elif seconds:
                minutes = 1
                seconds = 0

        return seconds + minutes * 60 + hours * 60 * 60 + days * 24 * 60 * 60


class TimeParser(object):
    fmt = '%Y-%m-%d %H:%M:%S'

    def __init__(self, hide_time, hide_date):
        self.hide_time = hide_time
        self.hide_date = hide_date

    def parse(self, data):
        if self.hide_time and self.hide_date:
            return None
        if self.hide_time:
            return TimeParser.parse_dt(data).date().isoformat()
        if self.hide_date:
            return TimeParser.parse_dt(data).time().isoformat()
        return TimeParser.parse_dt(data).isoformat()

    @staticmethod
    def parse_dt(data):
        return datetime.strptime(data, TimeParser.fmt)
