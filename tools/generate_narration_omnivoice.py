"""Regenerate the video narration with OmniVoice (the most human-like voice).

This script is meant to run on YOUR PC — Hugging Face is reachable there.
The model can't be downloaded on the small sandbox/AWS machine, but it runs
comfortably on your laptop (16GB RAM + 6GB GPU).

Setup (once):
    pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu121
    pip install omnivoice soundfile

Two ways to get a female voice:
  A) Voice cloning (BEST for Hindi): provide a clean 5-10 second
     recording of a woman's voice (with her permission!):
       python tools/generate_narration_omnivoice.py \
           --ref-audio meri_awaaz.wav \
           --ref-text "Write here exactly what is said in that recording"
  B) Voice design (no recording): --instruct "female, young adult,
     warm, clear" — note: design mode is trained on Chinese/English,
     so cloning is more stable for Hindi.

Output: brag-output/work/audio_omnivoice/scene1..8.wav
To rebuild the video, put them in brag-output/work/audio/ as sceneN.mp3
and run:
    python brag-output/work/build_video.py
"""
from __future__ import annotations

import argparse
import os
import sys

# Narration for the video's 8 scenes (Hindi in Devanagari — gives clear pronunciation)
SCENES = [
    "नमस्ते दोस्तों! ये है पीडीएफ क्वेश्चन आंसर सिस्टम। कोई भी पीडीएफ डालो, स्कैन्ड हो या स्क्रीनशॉट वाली, उसका सारा डेटा डेटाबेस में सेव होता है। फिर तुम हिंदी, हिंग्लिश या इंग्लिश में सवाल पूछ सकते हो, और जवाब मिलेगा पेज नंबर के साथ। चलो, शुरू से सेटअप सीखते हैं।",
    "सेटअप के लिए सिर्फ़ दो चीज़ें चाहिए, नोड जेएस और पाइथन। प्रोजेक्ट फ़ोल्डर में आकर एक ही कमांड चलानी है। लिनक्स या मैक पर बैश सेटअप वाली स्क्रिप्ट, और विंडोज़ पर सेटअप बैट फ़ाइल। ये स्क्रिप्ट ख़ुद सारी लाइब्रेरीज़ सही ऑर्डर में इंस्टॉल करके डेटाबेस भी तैयार कर देगी।",
    "अब सर्वर चलाने के लिए बस एनपीएम स्टार्ट लिखो। फिर ब्राउज़र में लोकलहोस्ट आठ हज़ार खोलो। यही स्क्रीन दिखेगी। ऊपर ओसीआर और डेटाबेस की जानकारी, लेफ़्ट में अपलोड और एआई पैनल, और राइट में चैट। अगर पुरानी पीडीएफ़ पहले से डेटाबेस में हैं, तो वो अपने आप आ जाएँगी।",
    "पहला स्टेप, पीडीएफ़ अपलोड करो। फ़ाइल को इस बॉक्स में ड्रैग एंड ड्रॉप कर दो, या क्लिक करके चूज़ करो। एक साथ कई फ़ाइलें भी चलेंगी। स्कैन्ड पीडीएफ़ है तो चिंता मत करो, ओसीआर अपने आप चल जाएगा। ये देखो, पीडीएफ़ प्रोसेस होकर डेटाबेस में सेव हो गई, पेजेस और चंक्स की गिनती के साथ।",
    "दूसरा स्टेप, सवाल पूछो। मैंने पूछा, यूपीआई क्यूआर कैसे बनता है? और जवाब आ गया। नीचे सोर्सेज़ खोलने पर फ़ाइल का नाम, पेज नंबर और मैच स्कोर दिखता है। मतलब तुम ख़ुद पीडीएफ़ खोलकर जवाब वेरीफ़ाई कर सकते हो।",
    "अगर चाहते हो जवाब साफ़ भाषा में लिखा हुआ मिले, तो एआई ऑन करो। लेफ़्ट पैनल में चार एआई हैं। पहले ओलामा, जो तुम्हारे अपने लैपटॉप पर बिल्कुल फ़्री चलता है, फिर जीएलएम, फिर एनवीडिया और जेमिनी। एक फ़ेल हुई तो दूसरी ख़ुद चल जाएगी। और सब फ़ेल हो जाएँ, तब भी डेटाबेस से जवाब मिल ही जाएगा। सिस्टम कभी रुकता नहीं।",
    "हर पीडीएफ़ का पूरा डेटा कभी भी देख सकते हो। डेटा देखो बटन से पेज-बाय-पेज टेक्स्ट खुलता है, और टीएक्सटी, सीएसवी या जेएसओएन में डाउनलोड भी कर सकते हो। यही डेटा प्रिज़्मा डेटाबेस में सेव रहता है। सर्वर बंद करके खोलने पर भी कहीं नहीं जाता।",
    "बस इतना ही था! सेटअप एक कमांड, रन एक कमांड, और फिर सिर्फ़ पीडीएफ़ डालो और सवाल पूछो। और हाँ, बाद में इसे एडब्ल्यूएस पर डिप्लॉय करने की पूरी गाइड भी रेपो में है। वीडियो अच्छा लगा हो तो ख़ुद ट्राय करके देखो। धन्यवाद!",
]


def main() -> int:
    ap = argparse.ArgumentParser(description="Generate video narration with OmniVoice")
    ap.add_argument("--ref-audio", help="5-10s reference recording (female voice, with permission)")
    ap.add_argument("--ref-text", help="Text spoken in the reference recording")
    ap.add_argument("--instruct", default="female, young adult, warm and clear voice",
                    help="Voice design description (when there is no ref-audio)")
    ap.add_argument("--model", default="k2-fsa/OmniVoice")
    ap.add_argument("--out", default="brag-output/work/audio_omnivoice")
    args = ap.parse_args()

    try:
        import soundfile as sf
        import torch
        from omnivoice import OmniVoice
    except ImportError:
        print("Install first:\n  pip install torch torchaudio omnivoice soundfile\n"
              "(for GPU, get the right CUDA build from the PyTorch site)")
        return 1

    device = "cuda:0" if torch.cuda.is_available() else "cpu"
    print(f"Loading model ({args.model}) on {device} ... "
          "the first run downloads it from Hugging Face (~2 GB).")
    model = OmniVoice.from_pretrained(
        args.model, device_map=device,
        dtype=torch.float16 if device.startswith("cuda") else torch.float32)

    prompt = None
    if args.ref_audio:
        if not os.path.exists(args.ref_audio):
            print(f"Reference audio not found: {args.ref_audio}")
            return 1
        prompt = model.create_voice_clone_prompt(
            ref_audio=args.ref_audio, ref_text=args.ref_text)
        print("Voice clone prompt is ready.")

    os.makedirs(args.out, exist_ok=True)
    for i, text in enumerate(SCENES, 1):
        if prompt is not None:
            audio = model.generate(text=text, voice_clone_prompt=prompt)
        else:
            audio = model.generate(text=text, instruct=args.instruct)
        path = os.path.join(args.out, f"scene{i}.wav")
        sf.write(path, audio[0], 24000)
        print(f"  scene{i}.wav  ({len(audio[0]) / 24000:.1f}s)")
    print(f"\nDone! Files: {args.out}/")
    print("To re-render the video, copy them as sceneN.mp3 "
          "into brag-output/work/audio/ and run:\n"
          "  python brag-output/work/build_video.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
