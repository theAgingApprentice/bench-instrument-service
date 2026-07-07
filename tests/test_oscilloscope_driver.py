"""Driver-level tests for the Siglent SDS1202X-E oscilloscope driver.

These tests assert on the literal SCPI strings sent via write()/query().
They exist because router- and contract-level tests mock the driver itself
and therefore cannot catch SCPI syntax bugs (e.g. the CPL coupling
D1M/A1M vs DC1M/AC1M mismatch found in July 2026 — see PR #25/#26).
"""

from unittest.mock import MagicMock, call

import pytest

from app.drivers.oscilloscope_siglent_sds1202xe import (
    OscilloscopeSiglentSDS1202XE,
    _read_ieee_block,
)


@pytest.fixture
def driver():
    """Driver instance with a mocked VISA resource, bypassing real connect()."""
    d = OscilloscopeSiglentSDS1202XE(ip="192.0.2.1")
    d._resource = MagicMock()
    return d


class TestConfigureChannelWireFormat:
    def test_coupling_dc_sends_d1m(self, driver):
        driver.configure_channel(channel=1, coupling="DC")
        driver._resource.write.assert_called_once_with("C1:CPL D1M")

    def test_coupling_ac_sends_a1m(self, driver):
        driver.configure_channel(channel=1, coupling="AC")
        driver._resource.write.assert_called_once_with("C1:CPL A1M")

    def test_coupling_gnd_sends_gnd(self, driver):
        driver.configure_channel(channel=2, coupling="GND")
        driver._resource.write.assert_called_once_with("C2:CPL GND")

    def test_invalid_coupling_raises_and_sends_nothing(self, driver):
        with pytest.raises(ValueError):
            driver.configure_channel(channel=1, coupling="BOGUS")
        driver._resource.write.assert_not_called()

    def test_scale_sends_vdiv(self, driver):
        driver.configure_channel(channel=1, scale=1.0)
        driver._resource.write.assert_called_once_with("C1:VDIV 1.0V")

    def test_offset_sends_ofst(self, driver):
        driver.configure_channel(channel=1, offset=-0.5)
        driver._resource.write.assert_called_once_with("C1:OFST -0.5V")

    def test_probe_sends_attn(self, driver):
        driver.configure_channel(channel=1, probe=10)
        driver._resource.write.assert_called_once_with("C1:ATTN 10")

    def test_all_channel_params_send_all_commands_in_order(self, driver):
        driver.configure_channel(channel=1, coupling="DC", scale=1.0, offset=0.0, probe=10)
        driver._resource.write.assert_has_calls([
            call("C1:CPL D1M"),
            call("C1:VDIV 1.0V"),
            call("C1:OFST 0.0V"),
            call("C1:ATTN 10"),
        ])


class TestConfigureTimebaseWireFormat:
    def test_scale_sends_tdiv(self, driver):
        driver.configure_timebase(scale=0.001)
        driver._resource.write.assert_called_once_with("TDIV 0.001S")

    def test_offset_sends_trdl(self, driver):
        driver.configure_timebase(offset=0.0)
        driver._resource.write.assert_called_once_with("TRDL 0.0S")


class TestConfigureTriggerWireFormat:
    def test_source_sends_trse(self, driver):
        driver.configure_trigger(source=1)
        driver._resource.write.assert_called_once_with("TRSE EDGE,SR,C1")

    def test_source_and_level_sends_both_in_order(self, driver):
        driver.configure_trigger(source=1, level=0.5)
        driver._resource.write.assert_has_calls([
            call("TRSE EDGE,SR,C1"),
            call("C1:TRLV 0.5V"),
        ])

    def test_mode_sends_trmd(self, driver):
        driver.configure_trigger(mode="AUTO")
        driver._resource.write.assert_called_once_with("TRMD AUTO")


class TestCaptureWaveformWireFormat:
    def test_sara_query_has_no_channel_prefix(self, driver):
        """SARA (sample rate) is a global acquisition property on this
        instrument, not per-channel -- 'C1:SARA?' hangs forever on real
        hardware (confirmed 5 July 2026 while running RC-Experiments
        against the real SDS1202X-E). Only bare 'SARA?' is valid.
        """
        responses = {
            "TRMD?": "TRMD AUTO",
            "C1:VDIV?": "C1:VDIV 500.00mV",
            "C1:OFST?": "C1:OFST 0.00V",
            "TDIV?": "TDIV 1.00ms",
            "C1:ATTN?": "C1:ATTN 10",
            "SARA?": "SARA 1.00GSa/s",
        }
        driver._resource.query.side_effect = lambda cmd: responses[cmd]
        driver._resource.read_raw.return_value = b"C1:WF DAT2,#14" + bytes([0, 1, 2, 3])

        driver.capture_waveform(channel=1)

        queried_commands = [call.args[0] for call in driver._resource.query.call_args_list]
        assert "SARA?" in queried_commands
        assert "C1:SARA?" not in queried_commands

    def test_stops_and_restores_trigger_mode(self, driver):
        """Reading the waveform buffer while the scope is actively
        acquiring (e.g. AUTO free-run) can return truncated/empty data --
        confirmed on real hardware 5 July 2026. capture_waveform() must
        stop acquisition before reading and restore the prior mode after.
        """
        responses = {
            "TRMD?": "TRMD AUTO",
            "C1:VDIV?": "C1:VDIV 500.00mV",
            "C1:OFST?": "C1:OFST 0.00V",
            "TDIV?": "TDIV 1.00ms",
            "C1:ATTN?": "C1:ATTN 10",
            "SARA?": "SARA 1.00GSa/s",
        }
        driver._resource.query.side_effect = lambda cmd: responses[cmd]
        driver._resource.read_raw.return_value = b"C1:WF DAT2,#14" + bytes([0, 1, 2, 3])

        driver.capture_waveform(channel=1)

        written_commands = [call.args[0] for call in driver._resource.write.call_args_list]
        assert "TRMD STOP" in written_commands
        assert "TRMD AUTO" in written_commands
        stop_index = written_commands.index("TRMD STOP")
        restore_index = written_commands.index("TRMD AUTO")
        assert stop_index < restore_index


class TestReadIeeeBlockChunking:
    """Regression tests for the 6 July 2026 bug: a single read_raw() call
    under-read a large binary waveform block, leaving bytes in the socket
    that corrupted the next SCPI command (a channel 2 TRMD? query came back
    as 'C1:WF DAT2,#9000000000\\nTRMD AUTO'). _read_ieee_block() must loop
    read_raw() until the byte count declared in the block's own header has
    actually been received.
    """

    def test_single_call_returns_full_block_unchanged(self):
        resource = MagicMock()
        header = b"C1:WF DAT2,#14"
        data = bytes([10, 20, 30, 40])
        resource.read_raw.return_value = header + data

        result = _read_ieee_block(resource)

        assert result == header + data
        resource.read_raw.assert_called_once()

    def test_loops_until_declared_byte_count_satisfied(self):
        """Simulates a VISA backend that dribbles a large binary block out
        over several read_raw() calls, with a chunk boundary falling in the
        middle of the header itself.
        """
        resource = MagicMock()
        payload = bytes(range(10))
        header = b"C1:WF DAT2,#210"  # n_digits=2, byte_count=10
        full = header + payload
        chunks = [full[:5], full[5:9], full[9:15], full[15:]]
        resource.read_raw.side_effect = chunks

        result = _read_ieee_block(resource)

        assert result == full
        assert resource.read_raw.call_count == len(chunks)

    def test_returns_exactly_declared_length_no_trailing_bytes(self):
        """If a read_raw() call happens to also grab bytes belonging to the
        next command's echo, the function must slice to exactly byte_count
        so nothing extra is mistaken for waveform data.
        """
        resource = MagicMock()
        header = b"C1:WF DAT2,#13"
        data = bytes([1, 2, 3])
        extra = b"\nTRMD AUTO"
        resource.read_raw.side_effect = [header + data + extra]

        result = _read_ieee_block(resource)

        assert result == header + data


class TestCaptureWaveformHandlesChunkedReads:
    def test_capture_waveform_reassembles_multi_chunk_binary_block(self, driver):
        """End-to-end regression test: capture_waveform() must still produce
        the correct waveform even when read_raw() only returns the block in
        pieces -- the exact real-world failure mode from 6 July 2026.
        """
        responses = {
            "TRMD?": "TRMD AUTO",
            "C1:VDIV?": "C1:VDIV 500.00mV",
            "C1:OFST?": "C1:OFST 0.00V",
            "TDIV?": "TDIV 1.00ms",
            "C1:ATTN?": "C1:ATTN 10",
            "SARA?": "SARA 1.00GSa/s",
        }
        driver._resource.query.side_effect = lambda cmd: responses[cmd]

        payload = bytes(range(6))
        header = b"C1:WF DAT2,#16"  # n_digits=1, byte_count=6
        full = header + payload
        driver._resource.read_raw.side_effect = [full[:6], full[6:10], full[10:]]

        result = driver.capture_waveform(channel=1)

        assert result["num_points"] == 6
        assert driver._resource.read_raw.call_count == 3
