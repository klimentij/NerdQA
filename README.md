# ADE


# Setting up Redis for LiteLLM Caching

This guide explains how to set up Redis for use with LiteLLM's caching feature on Ubuntu and macOS.

## Ubuntu

1. Install Redis:
   ```bash
   sudo apt-get update
   sudo apt-get install redis-server
   ```

2. Edit the Redis configuration file:
   ```bash
   sudo nano /etc/redis/redis.conf
   ```

3. Add or modify these lines in the configuration file:
   ```
   dir /path/to/your/cache/directory
   appendonly yes
   appendfilename "appendonly.aof"
   dbfilename dump.rdb
   ```

4. Create the cache directory:
   ```bash
   sudo mkdir -p /path/to/your/cache/directory
   sudo chown redis:redis /path/to/your/cache/directory
   ```

5. Restart Redis:
   ```bash
   sudo systemctl restart redis-server
   ```

6. Verify Redis is running:
   ```bash
   redis-cli ping
   ```
   You should see "PONG" as the response.

## macOS

1. Install Redis using Homebrew:
   ```bash
   brew install redis
   ```

2. Edit the Redis configuration file:
   ```bash
   nano /opt/homebrew/etc/redis.conf
   ```

3. Add or modify these lines in the configuration file:
   ```
   dir /Users/yourusername/path/to/cache/directory
   appendonly yes
   appendfilename "appendonly.aof"
   dbfilename dump.rdb
   daemonize yes
   pidfile /Users/yourusername/path/to/cache/directory/redis.pid
   logfile /Users/yourusername/path/to/cache/directory/redis.log
   ```

4. Create the cache directory:
   ```bash
   mkdir -p /Users/yourusername/path/to/cache/directory
   ```

5. Start Redis manually:
   ```bash
   /opt/homebrew/opt/redis/bin/redis-server /opt/homebrew/etc/redis.conf
   ```

6. Verify Redis is running:
   ```bash
   redis-cli ping
   ```
   You should see "PONG" as the response.

7. To stop Redis:
   ```bash
   redis-cli shutdown
   ```

8. To restart Redis:
   First, stop Redis if it's running:
   ```bash
   redis-cli shutdown
   ```
   Then start it again:
   ```bash
   /opt/homebrew/opt/redis/bin/redis-server /opt/homebrew/etc/redis.conf
   ```

9. (Optional) To create a simple script for starting Redis:
   Create a file named `start_redis.sh` with the following content:
   ```bash
   #!/bin/bash
   /opt/homebrew/opt/redis/bin/redis-server /opt/homebrew/etc/redis.conf
   ```
   Make it executable:
   ```bash
   chmod +x start_redis.sh
   ```
   You can now start Redis by running this script:
   ```bash
   ./start_redis.sh
   ```

## Configuring LiteLLM

After setting up Redis, update your `litellm.yml` configuration:

```yaml
litellm_settings:
  cache: True
  cache_params:
    type: redis
    host: localhost
    port: 6379
    password: "" # leave empty if no password set
    ttl: 25920000  # 300 days in seconds (300 * 24 * 60 * 60)
```

This configuration will enable LiteLLM to use your local Redis instance for caching.
```
