import server


def main():
    """Entry point for the undesirables-mcp console command."""
    server.enable_memory_lock()
    server.main()
    server.mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
