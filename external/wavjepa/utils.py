import torch

def normalize(audio):
    mean = audio.mean(dim=(-2, -1), keepdim=True)
    std = audio.std(dim=(-2, -1), keepdim=True)
    audio = (audio - mean) / (std + 1e-5) # Add epsilon for stability
    return audio

def calculate_padding_mask(pad_frames, total_frames, sr, output_steps, process_seconds, device, B):
    # How many 2 seconds chunks does this audio have?
    # Find it and then multiply by the output_steps.
    total_frames = int((total_frames / sr) / process_seconds)
    total_output_steps = output_steps * total_frames
    mask = torch.zeros((B, total_output_steps), dtype = torch.bool, device = device)

    # Check the number of padding tokens that we have in the audio.
    output_sr = int(output_steps / process_seconds)
    pad_seconds = pad_frames / sr
    pad_steps = int(pad_seconds * output_sr)
    # Create the mask

    mask[..., total_output_steps - pad_steps:] = True 
    return mask, total_output_steps - pad_steps


def get_timestamps(sample_rate, B, input_audio_len, x):
    audio_len = input_audio_len
    sec = audio_len / sample_rate
    x_len = x.shape[1]
    step = sec / x_len * 1000  # sec -> ms
    ts = torch.tensor([step * i for i in range(x_len)]).unsqueeze(0)
    ts = ts.repeat(B, 1)
    return ts