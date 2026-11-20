# Audition Operator

The `audition` operator allows you to evaluate generated images against various criteria. Below are the available options and usage examples.

## Options

- `--renderer <type>`: Choose the rendering backend. Supported types are `default`, `sam`, and `custom`.
- `--checkpoint <path>`: Path to the model checkpoint.
- `--watermark <bool>`: Enable or disable watermarking of the output images.

## Usage

```bash
kaine audition --renderer default --checkpoint ./models/checkpoint.pt --watermark true
```

### Note on `--renderer sam`

- The `sam` renderer **requires a version 2 checkpoint**. Ensure you provide a compatible checkpoint file.
- When using `--renderer sam`, **no implicit watermark is applied**. If you need a watermark, you must enable it explicitly using the `--watermark` flag.

## Examples

```bash
# Use the SAM renderer with an explicit watermark
kaine audition --renderer sam --checkpoint ./models/checkpoint_v2.pt --watermark true
```

```bash
# Use the default renderer with automatic watermarking
kaine audition --renderer default --checkpoint ./models/checkpoint.pt
```

Refer to the full documentation for more details on each option and advanced configurations.