from pytubefix import YouTube
import os

def download_video():
    try:
        url = input("Enter YouTube URL: ")
        yt = YouTube(url)
        
        print(f"Title: {yt.title}")
        print("1. MP3 (Audio only)")
        print("2. MP4 (Video - 720p)")
        choice = input("Choice (1 or 2): ")

        if choice == '1':
            print("Downloading audio...")
            stream = yt.streams.get_audio_only()
            out_file = stream.download()
            
            # Change file extension to .mp3
            base, ext = os.path.splitext(out_file)
            new_file = base + '.mp3'
            os.rename(out_file, new_file)
            print(f"✅ Saved as: {new_file}")

        elif choice == '2':
            print("Downloading video...")
            stream = yt.streams.get_highest_resolution()
            stream.download()
            print(f"✅ Saved: {yt.title}.mp4")
        
        else:
            print("Invalid option selected.")

    except Exception as e:
        print(f"❌ Error: {e}")

if __name__ == "__main__":
    download_video()