from __future__ import annotations

ROPI_ROLE = "Humanoid robot receptionist for Sari Technology Global"

# This field is intentionally limited to agent identity, domain, personality,
# and speaking style. Tool use, memory, safety, external data, and runtime
# behavior are injected by VerbaNode's hidden prompt composer.
ROPI_SYSTEM_PROMPT = """You are Ropi, a humanoid robot receptionist developed by Sari Technology Global.

Your personality is friendly, attentive, practical, and professional. Speak as Ropi with clear, concise, natural responses. Help visitors learn about Sari Technology Global, understand Ropi, and navigate the interactions presented to them.

Ropi is designed for conversation, visitor guidance, information and advertisement display, and photobooth experiences. Do not repeatedly introduce yourself or recite your capabilities unless the user asks."""

ROPI_GREETING = (
    "Hello! I'm Ropi from Sari Technology Global. How can I help you today?"
)

ROPI_LLM_MODEL = "qwen3.5:0.8b"
ROPI_TEMPERATURE = 0.2
ROPI_TOP_P = 0.8
ROPI_MAX_TOKENS = 224
ROPI_CONTEXT_SIZE = 4096


ROPI_ID_ROLE = "Resepsionis robot humanoid untuk Sari Technology Global"

ROPI_ID_SYSTEM_PROMPT = """Anda adalah Ropi, robot humanoid resepsionis yang dikembangkan oleh Sari Teknologi Global.

Kepribadian Anda ramah, penuh perhatian, praktis, dan profesional. Berbicaralah sebagai Ropi menggunakan Bahasa Indonesia yang jelas, ringkas, dan alami. Bantu pengunjung mengenal Sari Teknologi Global, memahami Ropi, dan menggunakan interaksi yang tersedia.

Ropi dirancang untuk percakapan, panduan pengunjung, tampilan informasi dan iklan, serta pengalaman photobooth. Jangan terus-menerus memperkenalkan diri atau menyebutkan semua kemampuan kecuali pengguna menanyakannya."""

ROPI_ID_GREETING = "Halo! Saya Ropi dari Sari Teknologi Global. Ada yang bisa saya bantu hari ini?"
ROPI_ID_EDGE_VOICE = "id-ID-GadisNeural"
ROPI_ID_STT_MODEL = "Whisper-base"


# Default direct-speech scripts. Scripts own their language and TTS settings;
# they do not inherit the active agent voice.
DEFAULT_INTRO_EN_TITLE = "Introduction"
DEFAULT_INTRO_EN_TEXT = "Hello and welcome. This is the VerbaNode voice assistant."
DEFAULT_INTRO_ID_TITLE = "Introduksi"
DEFAULT_INTRO_ID_TEXT = "Halo dan selamat datang. Ini adalah VerbaNode."

DEFAULT_COMPANY_INFO_TITLE = "Sari Teknologi Company Profile"
DEFAULT_COMPANY_INFO_CONTENT = """Sari Teknologi is an Indonesian technology company specializing in robotics research, robot manufacturing, artificial intelligence, and robotics education. With more than 15 years of experience, the company is committed to accelerating technological innovation by developing intelligent robotic solutions and cultivating future talent through hands-on education and training programs.

The company provides end-to-end robotics solutions for industrial automation, education, research, and specialized applications. Its expertise spans AI-powered robotics, autonomous systems, embedded systems, software engineering, mechanical and electrical design, 3D modeling, and custom robotic platforms tailored to industry requirements.

In addition to manufacturing, Sari Teknologi operates one of Indonesia's leading robotics education centers, offering comprehensive programs in robotics, programming, artificial intelligence, machine learning, IoT, and automation. These programs are designed to equip students, professionals, and institutions with the practical skills needed to thrive in the era of Industry 4.0.

Driven by a multidisciplinary team of engineers, researchers, designers, and educators, Sari Teknologi continuously transforms innovative ideas into real-world solutions that enhance productivity, improve learning experiences, and support digital transformation across multiple industries.

With a strong focus on quality, innovation, and collaboration, Sari Teknologi partners with government institutions, universities, and private organizations to develop cutting-edge robotic technologies that contribute to Indonesia's growing technology ecosystem and prepare society for the future of intelligent automation."""
