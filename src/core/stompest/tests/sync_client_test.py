import logging
import unittest

from stompest.config import StompConfig
from stompest.error import StompConnectionError, StompProtocolError
from stompest.protocol import commands, StompFrame, StompSpec, StompSession
from stompest.sync import Stomp

from stompest.tests import mock

logging.basicConfig(level=logging.DEBUG)

HOST = 'fakeHost'
PORT = 61613

CONFIG = StompConfig('tcp://%s:%s' % (HOST, PORT), check=False)

class SimpleStompTest(unittest.TestCase):
    def _get_transport_mock(self, receive=None, config=None):
        stomp = Stomp(config or CONFIG)
        stomp._transport = mock.Mock()
        if receive:
            stomp._transport.receive.return_value = receive
        return stomp

    def _get_connect_mock(self, receive=None, config=None):
        stomp = Stomp(config or CONFIG)
        stomp._transportFactory = mock.Mock()
        transport = stomp._transportFactory.return_value = mock.Mock()
        transport.host = 'mock'
        transport.port = 0
        if receive:
            transport.receive.return_value = receive
        return stomp

    def _get_timeouting_connect_mock(self):
        stomp = Stomp(CONFIG)
        stomp._transportFactory = mock.Mock()
        transport = stomp._transportFactory.return_value = mock.Mock()
        transport.host = 'mock'
        transport.port = 0
        transport.canRead.return_value = False
        return stomp

    def test_receiveFrame(self):
        frame_ = StompFrame(StompSpec.MESSAGE, {'x': 'y'}, b'testing 1 2 3')
        stomp = self._get_transport_mock(frame_)
        frame = stomp.receiveFrame()
        self.assertEqual(frame_, frame)
        self.assertEqual(1, stomp._transport.receive.call_count)

    def test_canRead_raises_exception_before_connect(self):
        stomp = Stomp(CONFIG)
        self.assertRaises(Exception, stomp.canRead)

    def test_send_raises_exception_before_connect(self):
        stomp = Stomp(CONFIG)
        self.assertRaises(StompConnectionError, stomp.send, '/queue/foo', 'test message')

    def test_subscribe_raises_exception_before_connect(self):
        stomp = Stomp(CONFIG)
        self.assertRaises(Exception, stomp.subscribe, '/queue/foo')

    def test_disconnect_raises_exception_before_connect(self):
        stomp = Stomp(CONFIG)
        self.assertRaises(Exception, stomp.disconnect)

    def test_connect_raises_exception_for_bad_host(self):
        stomp = Stomp(StompConfig('tcp://nosuchhost:2345'))
        self.assertRaises(Exception, stomp.connect)

    def test_closes_session_on_read_timeout_during_connect(self):
        stomp = self._get_timeouting_connect_mock()
        with mock.patch.object(StompSession, "close") as close_mock:
            self.assertRaises(Exception, stomp.connect)
        close_mock.assert_called_once()


    def test_connect_raises_exception_for_bad_host(self):
        stomp = Stomp(StompConfig('tcp://nosuchhost:2345'))
        self.assertRaises(Exception, stomp.connect)

    def test_error_frame_after_connect_raises_StompProtocolError(self):
        stomp = self._get_connect_mock(StompFrame(StompSpec.ERROR, body=b'fake error'))
        self.assertRaises(StompProtocolError, stomp.connect)
        self.assertEqual(stomp._transport.receive.call_count, 1)

    def test_connect_when_connected_raises_StompConnectionError(self):
        stomp = self._get_transport_mock()
        self.assertRaises(StompConnectionError, stomp.connect)

    def test_connect_writes_correct_frame(self):
        login = 'curious'
        passcode = 'george'
        stomp = self._get_connect_mock(StompFrame(StompSpec.CONNECTED, {StompSpec.SESSION_HEADER: '4711'}))
        stomp._config.login = login
        stomp._config.passcode = passcode
        stomp.connect()
        args, _ = stomp._transport.send.call_args
        sentFrame = args[0]
        self.assertEqual(StompFrame(StompSpec.CONNECT, {StompSpec.LOGIN_HEADER: login, StompSpec.PASSCODE_HEADER: passcode}), sentFrame)

    def test_send_writes_correct_frame(self):
        destination = '/queue/foo'
        message = b'test message'
        headers = {'foo': 'bar', 'fuzz': 'ball'}
        stomp = self._get_transport_mock()
        stomp.send(destination, message, headers)
        args, _ = stomp._transport.send.call_args
        sentFrame = args[0]
        self.assertEqual(StompFrame('SEND', {StompSpec.DESTINATION_HEADER: destination, 'foo': 'bar', 'fuzz': 'ball'}, message), sentFrame)

    def test_subscribe_writes_correct_frame(self):
        destination = '/queue/foo'
        headers = {'foo': 'bar', 'fuzz': 'ball'}
        stomp = self._get_transport_mock()
        stomp.subscribe(destination, headers)
        args, _ = stomp._transport.send.call_args
        sentFrame = args[0]
        self.assertEqual(StompFrame(StompSpec.SUBSCRIBE, {StompSpec.DESTINATION_HEADER: destination, 'foo': 'bar', 'fuzz': 'ball'}), sentFrame)

    def test_subscribe_matching_and_corner_cases(self):
        destination = '/queue/foo'
        headers = {'foo': 'bar', 'fuzz': 'ball'}
        stomp = self._get_transport_mock()
        token = stomp.subscribe(destination, headers)
        self.assertEqual(token, (StompSpec.DESTINATION_HEADER, destination))
        self.assertEqual(stomp.message(StompFrame(StompSpec.MESSAGE, {StompSpec.MESSAGE_ID_HEADER: '4711', StompSpec.DESTINATION_HEADER: destination})), token)
        self.assertRaises(StompProtocolError, stomp.message, StompFrame(StompSpec.MESSAGE, {StompSpec.MESSAGE_ID_HEADER: '4711', StompSpec.DESTINATION_HEADER: 'unknown'}))
        self.assertRaises(StompProtocolError, stomp.message, StompFrame(StompSpec.MESSAGE, {StompSpec.DESTINATION_HEADER: destination}))

    def test_stomp_version_1_1(self):
        destination = '/queue/foo'
        stomp = self._get_transport_mock(config=StompConfig('tcp://%s:%s' % (HOST, PORT), version=StompSpec.VERSION_1_1, check=False))
        stomp._transport = mock.Mock()
        frame = StompFrame(StompSpec.MESSAGE, {StompSpec.MESSAGE_ID_HEADER: '4711', StompSpec.DESTINATION_HEADER: destination})
        self.assertRaises(StompProtocolError, stomp.nack, frame)
        frame = StompFrame(StompSpec.MESSAGE, {StompSpec.MESSAGE_ID_HEADER: '4711', StompSpec.DESTINATION_HEADER: destination, StompSpec.SUBSCRIPTION_HEADER: '0815'}, version=StompSpec.VERSION_1_1)
        stomp.nack(frame, receipt='123')
        args, _ = stomp._transport.send.call_args
        sentFrame = args[0]
        self.assertEqual(commands.nack(frame, receipt='123'), sentFrame)

    def test_ack_writes_correct_frame(self):
        id_ = '12345'
        stomp = self._get_transport_mock()
        stomp.ack(StompFrame(StompSpec.MESSAGE, {StompSpec.MESSAGE_ID_HEADER: id_}, b'blah'))
        args, _ = stomp._transport.send.call_args
        sentFrame = args[0]
        self.assertEqual(StompFrame(StompSpec.ACK, {StompSpec.MESSAGE_ID_HEADER: id_}), sentFrame)

    def test_transaction_writes_correct_frames(self):
        transaction = '4711'
        stomp = self._get_transport_mock()
        for (method, command) in [
            (stomp.begin, StompSpec.BEGIN), (stomp.commit, StompSpec.COMMIT),
            (stomp.begin, StompSpec.BEGIN), (stomp.abort, StompSpec.ABORT)
        ]:
            method(transaction)
            args, _ = stomp._transport.send.call_args
            sentFrame = args[0]
            self.assertEqual(StompFrame(command, {StompSpec.TRANSACTION_HEADER: transaction}), sentFrame)

        with stomp.transaction(transaction):
            args, _ = stomp._transport.send.call_args
            sentFrame = args[0]
            self.assertEqual(StompFrame(StompSpec.BEGIN, {StompSpec.TRANSACTION_HEADER: transaction}), sentFrame)

        args, _ = stomp._transport.send.call_args
        sentFrame = args[0]
        self.assertEqual(StompFrame(StompSpec.COMMIT, {StompSpec.TRANSACTION_HEADER: transaction}), sentFrame)

        try:
            with stomp.transaction(transaction):
                raise
        except:
            args, _ = stomp._transport.send.call_args
            sentFrame = args[0]
            self.assertEqual(StompFrame(StompSpec.ABORT, {StompSpec.TRANSACTION_HEADER: transaction}), sentFrame)

if __name__ == '__main__':
    unittest.main()
