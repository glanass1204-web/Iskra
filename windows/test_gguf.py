import os
import struct
import tempfile
import unittest

import iskra_gguf as g


def _s(x):
    b = x.encode()
    return struct.pack('<Q', len(b)) + b


def make(path, kv):
    data = b'GGUF' + struct.pack('<IQQ', 3, 0, len(kv)) + b''.join(_s(k) + struct.pack('<I', t) + v for k, t, v in kv)
    with open(path, 'wb') as f:
        f.write(data)


class Header(unittest.TestCase):
    def test_mtp_detected_and_arrays_skipped(self):
        d = tempfile.mkdtemp()
        with_mtp, without = os.path.join(d, 'a.gguf'), os.path.join(d, 'b.gguf')
        common = [('general.architecture', 8, _s('qwen35')),
                  ('tokenizer.ggml.tokens', 9, struct.pack('<IQ', 8, 2) + _s('а') + _s('бв')),
                  ('tokenizer.ggml.scores', 9, struct.pack('<IQ', 6, 2) + struct.pack('<2f', 1, 2))]
        make(with_mtp, common + [('qwen35.nextn_predict_layers', 4, struct.pack('<I', 1))])
        make(without, common)
        self.assertTrue(g.has_mtp(with_mtp))
        self.assertFalse(g.has_mtp(without))
        self.assertEqual(g.metadata(without)['general.architecture'], 'qwen35')

    def test_not_gguf(self):
        p = os.path.join(tempfile.mkdtemp(), 'x.gguf')
        open(p, 'wb').write(b'garbage')
        self.assertFalse(g.has_mtp(p))
        self.assertFalse(g.has_mtp(os.path.join(tempfile.mkdtemp(), 'missing.gguf')))


if __name__ == '__main__':
    unittest.main()
