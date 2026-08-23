try:
    from app.main import main
except ImportError:
    from main import main


if __name__ == "__main__":
    main()