MODERATOR = "Moderator"
INTERRUPT, WAIT = "<|interrupt|>", "<|wait|>"

def render(transcript, partial=None, next_speaker=None):
    s = "".join(f"<|im_start|>{who}\n{txt}<|im_end|>\n" for who, txt in transcript)
    if partial:
        who, txt = partial
        s += f"<|im_start|>{who}\n{txt}"
        if next_speaker:
            s += "<|im_end|>\n"
    if next_speaker:
        s += f"<|im_start|>{next_speaker}\n"
    return s