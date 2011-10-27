import datetime, time
import re
import sys

import simplejson

from dogapi.v1 import EventService

from dogshell.common import report_errors, report_warnings, CommandLineClient

def prettyprint_event(event):
    title = event['title'] or ''
    handle = event.get('handle', '')
    date = event['date_happened']
    dt = datetime.datetime.fromtimestamp(date)
    link = event['url']
    print (title + ' (' + handle + ')').strip()
    print dt.isoformat(' ') + ' | '+ link

def print_event(event):
    prettyprint_event(event)

def prettyprint_event_details(event):
    prettyprint_event(event)

def print_event_details(event):
    prettyprint_event(event)

time_pat = re.compile(r'(?P<delta>[0-9]*\.?[0-9]+)(?P<unit>[mhd])')
def parse_time(timestring):
    now = time.mktime(datetime.datetime.now().timetuple())
    if timestring is None:
        t = now
    else:
        try:
            t = int(timestring)
        except:
            match = time_pat.match(timestring)
            if match is None:
                raise Exception
            delta = float(match.group('delta'))
            unit = match.group('unit')
            if unit == 'm':
                delta = delta * 60
            if unit == 'h':
                delta = delta * 60 * 60
            if unit == 'd':
                delta = delta * 60 * 60 * 24
            t =  now - int(delta)
    return int(t)

class EventClient(CommandLineClient):

    def __init__(self, config):
        self.config = config

    def setup_parser(self, subparsers):
        parser = subparsers.add_parser('event', help='Post events, get event details, and view the event stream.')
        verb_parsers = parser.add_subparsers(title='Verbs')

        post_parser = verb_parsers.add_parser('post', help='Post events.')
        post_parser.add_argument('title', help='event title')
        post_parser.add_argument('--date_happened', help='POSIX timestamp when the event occurred. if unset defaults to the current time.')
        post_parser.add_argument('--handle', help='user to post as. if unset, submits as the generic API user.')
        post_parser.add_argument('--priority', help='"normal" or "low". defaults to "normal"')
        post_parser.add_argument('--related_event_id', help='event to post as a child of. if unset, posts a top-level event')
        post_parser.add_argument('--tags', help='comma separated list of tags')
        post_parser.add_argument('message', help='event message body. if unset, reads from stdin.', nargs="?")
        post_parser.set_defaults(func=self._post)

        show_parser = verb_parsers.add_parser('show', help='Show event details.')
        show_parser.add_argument('event_id', help='event to show')
        show_parser.set_defaults(func=self._show)

        stream_parser = verb_parsers.add_parser('stream', help='Delete comments.', description="Stream start and end times can be specified as either a POSIX timestamp (e.g. the output of `date +%s`) or as a period of time in the past (e.g. '5m', '6h', '3d').")
        stream_parser.add_argument('start', help='start date for the stream request')
        stream_parser.add_argument('end', help='end date for the stream request (defaults to "now")', nargs='?')
        stream_parser.add_argument('--priority', help='filter by priority. "normal" or "low". defaults to "normal"')
        stream_parser.add_argument('--sources', help='comma separated list of sources to filter by')
        stream_parser.add_argument('--tags', help='comma separated list of tags to filter by')
        stream_parser.set_defaults(func=self._stream)

    def _post(self, args):
        format = args.format
        message = args.message
        if message is None:
            message = sys.stdin.read()
        svc = EventService(self.config['apikey'], self.config['appkey'])
        if args.tags is not None:
            tags = [t.strip() for t in args.tags.split(',')]
        else:
            tags = None
        res = svc.post(args.title,
                       message,
                       args.date_happened,
                       args.handle,
                       args.priority,
                       args.related_event_id,
                       tags)
        report_warnings(res)
        report_errors(res)
        if format == 'pretty':
            prettyprint_event(res['event'])
        elif format == 'raw':
            print simplejson.dumps(res)
        else:
            print_event(res['event'])

    def _show(self, args):
        format = args.format
        svc = EventService(self.config['apikey'], self.config['appkey'])
        res = svc.get(args.event_id)
        report_warnings(res)
        report_errors(res)
        if format == 'pretty':
            prettyprint_event_details(res['event'])
        elif format == 'raw':
            print simplejson.dumps(res)
        else:
            print_event_details(res['event'])

    def _stream(self, args):
        format = args.format
        svc = EventService(self.config['apikey'], self.config['appkey'])
        if args.sources is not None:
            sources = [s.strip() for s in args.sources.split(',')]
        else:
            sources = None
        if args.tags is not None:
            tags = [t.strip() for t in args.tags.split(',')]
        else:
            tags = None
        start = parse_time(args.start)
        end = parse_time(args.end)
        res = svc.query(start, end, args.priority, sources, tags)
        report_warnings(res)
        report_errors(res)
        if format == 'pretty':
            for event in res['events']:
                prettyprint_event(event)
                print
        elif format == 'raw':
            print simplejson.dumps(res)
        else:
            for event in res['events']:
                print_event(event)
                print