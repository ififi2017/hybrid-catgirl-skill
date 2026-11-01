import io,os,sys,tempfile,unittest,wave,base64
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from maomao_companion.providers import gemini_audio,GEMINI_TTS_MODEL

class GeminiSpeechTests(unittest.TestCase):
    def test_aoede_interactions_payload_and_wav(self):
        with tempfile.TemporaryDirectory() as folder,patch.dict(os.environ,{'GEMINI_API_KEY':'synthetic-key'}):
            stream=io.BytesIO()
            with wave.open(stream,'wb') as w:w.setnchannels(1);w.setsampwidth(2);w.setframerate(24000);w.writeframes(b'\0'*4800)
            payloads=[]
            def request(url,body,headers,timeout):
                payloads.append(body)
                return {'steps':[{'type':'model_output','content':[{'type':'audio','mime_type':'audio/wav','data':base64.b64encode(stream.getvalue()).decode()}]}]}
            with patch('maomao_companion.providers.request_json',request):
                path=Path(gemini_audio('こんにちは',Path(folder)/'voice.wav','wav'))
            self.assertTrue(path.read_bytes().startswith(b'RIFF'))
            self.assertEqual(payloads[0]['model'],GEMINI_TTS_MODEL)
            self.assertEqual(payloads[0]['generation_config']['speech_config'],[{'voice':'Aoede'}])
            self.assertEqual(payloads[0]['input'][0]['content'][0]['text'],'こんにちは')
    def test_missing_audio_fails_without_claiming_success(self):
        with tempfile.TemporaryDirectory() as folder,patch.dict(os.environ,{'GEMINI_API_KEY':'synthetic-key'}),patch('maomao_companion.providers.request_json',return_value={'steps':[]}):
            with self.assertRaises(RuntimeError):gemini_audio('hi',Path(folder)/'voice.wav','wav')
