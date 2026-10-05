"""Audio warning node with text-to-speech (dissertation Section 4.8).

Speaks the robot's warnings. Backend chain (first available wins):

  1. piper      - neural TTS, natural voice, fully offline, speaks the
                  actual message text (including the camera/room name).
                  pip install piper-tts + a voice model in voices/
                  (see 'piper_model' parameter).
  2. espeak-ng  - offline formant TTS (robotic but dynamic).
                  Install with: sudo apt install espeak-ng
  3. audio file - pre-generated speech in the package audio/ folder:
                  {kind}.mp3 via gst-play-1.0, or {kind}.wav via aplay.
                  Generate with tools/generate_audio_wavs.py (gTTS).
  4. log only   - warning text is logged (always happens regardless).
"""

import json
import os
import shutil
import subprocess

import rclpy
from ament_index_python.packages import get_package_share_directory
from rclpy.node import Node
from std_msgs.msg import String


class AudioWarningNode(Node):

    def __init__(self):
        super().__init__('audio_warning_node')

        default_dir = ''
        try:
            default_dir = os.path.join(
                get_package_share_directory('yoru_core'), 'audio')
        except Exception:  # noqa: BLE001 - share dir may not exist yet
            pass

        self.declare_parameter('use_audio', True)
        self.declare_parameter('audio_dir', default_dir)
        self.declare_parameter('aplay_device', 'default')
        # Piper neural voice (natural). Model + .onnx.json expected together.
        self.declare_parameter('piper_model', os.path.expanduser(
            '~/Yoru_bot_V2/voices/en_GB-alba-medium.onnx'))
        self.declare_parameter('espeak_speed', 140)
        self.declare_parameter('espeak_amplitude', 200)
        self.declare_parameter('espeak_voice', 'en')
        # Distributed deployment: the server (CCTV side) speaks the PA
        # announcement, the robot's speaker delivers the direct warning.
        self.declare_parameter('speak_pa', True)
        self.declare_parameter('speak_direct', True)

        self.espeak = shutil.which('espeak-ng') or shutil.which('espeak')
        self.gst_play = shutil.which('gst-play-1.0')
        piper_exe = shutil.which('piper') or os.path.expanduser('~/.local/bin/piper')
        piper_model = os.path.expanduser(self.get_parameter('piper_model').value)
        self.piper = None
        if os.path.isfile(piper_exe) and os.path.isfile(piper_model) \
                and os.path.isfile(piper_model + '.json'):
            self.piper = (piper_exe, piper_model)
        self.proc = None  # current playback process; new warning preempts
        # Evaluation instrumentation: one record per warning delivered
        self.event_pub = self.create_publisher(
            String, '/compliance/audio_event', 50)

        if self.get_parameter('speak_pa').value:
            self.create_subscription(String, '/compliance/pa_warning',
                                     lambda m: self.play('pa_warning', m), 10)
        if self.get_parameter('speak_direct').value:
            self.create_subscription(String, '/compliance/direct_warning',
                                     lambda m: self.play('direct_warning', m), 10)

        if not self.get_parameter('use_audio').value:
            backend = 'log-only (use_audio: false)'
        elif self.piper:
            backend = f'piper neural TTS ({os.path.basename(self.piper[1])})'
        elif self.espeak:
            backend = f'espeak TTS ({self.espeak}) - install piper-tts ' \
                      '+ a voice model for a natural voice'
        else:
            backend = 'audio files (install piper-tts or espeak-ng for ' \
                      'dynamic speech)'
        self.get_logger().info(f'Audio warning node ready - backend: {backend}')

    def play(self, kind, msg):
        try:
            payload = json.loads(msg.data)
            text = payload.get('message', msg.data)
        except ValueError:
            payload, text = {}, msg.data
        self.get_logger().warn(f'[{kind.upper()}] {text}')
        self.publish_event(kind, text, payload)

        if not self.get_parameter('use_audio').value:
            return

        # Stop any still-running announcement before starting a new one
        if self.proc is not None and self.proc.poll() is None:
            self.proc.terminate()

        if self.piper:
            exe, model = self.piper
            stem = f'/tmp/yoru_tts_{os.getpid()}'
            with open(stem + '.txt', 'w', encoding='utf-8') as f:
                f.write(text)
            player = (f'"{self.gst_play}" -q' if self.gst_play
                      else 'aplay -q -D '
                           + self.get_parameter('aplay_device').value)
            self._run(['bash', '-c',
                       f'"{exe}" -m "{model}" -c "{model}.json" '
                       f'-i {stem}.txt -f {stem}.wav 2>/dev/null '
                       f'&& exec {player} {stem}.wav'])
            return

        if self.espeak:
            self._run([self.espeak,
                       '-s', str(self.get_parameter('espeak_speed').value),
                       '-a', str(self.get_parameter('espeak_amplitude').value),
                       '-v', self.get_parameter('espeak_voice').value,
                       text])
            return

        audio_dir = self.get_parameter('audio_dir').value
        mp3 = os.path.join(audio_dir, f'{kind}.mp3')
        wav = os.path.join(audio_dir, f'{kind}.wav')
        if self.gst_play and os.path.isfile(mp3):
            self._run([self.gst_play, '-q', mp3])
        elif os.path.isfile(wav):
            self._run(['aplay', '-q', '-D',
                       self.get_parameter('aplay_device').value, wav])
        else:
            self.get_logger().warn(
                f'No TTS engine and no audio file for "{kind}" in {audio_dir}')

    def backend(self, kind):
        if not self.get_parameter('use_audio').value:
            return 'log_only'
        if self.piper:
            return 'piper'
        if self.espeak:
            return 'espeak'
        audio_dir = self.get_parameter('audio_dir').value
        if (self.gst_play and os.path.isfile(os.path.join(audio_dir, f'{kind}.mp3'))) \
                or os.path.isfile(os.path.join(audio_dir, f'{kind}.wav')):
            return 'audio_file'
        return 'none'

    def publish_event(self, kind, text, payload):
        event = String()
        event.data = json.dumps({
            'stamp': self.get_clock().now().nanoseconds * 1e-9,
            'kind': kind,                      # pa_warning | direct_warning
            'backend': self.backend(kind),
            'track_id': payload.get('track_id') if isinstance(payload, dict) else None,
            'room': payload.get('room') if isinstance(payload, dict) else None,
            'event_class': payload.get('event_class') if isinstance(payload, dict) else None,
            'message': text,
        })
        self.event_pub.publish(event)

    def _run(self, cmd):
        try:
            self.proc = subprocess.Popen(
                cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError as exc:
            self.get_logger().error(f'Audio playback failed: {exc}')


def main(args=None):
    rclpy.init(args=args)
    node = AudioWarningNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.try_shutdown()


if __name__ == '__main__':
    main()
