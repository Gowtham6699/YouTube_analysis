#!/usr/bin/env python
# coding: utf-8

# In[1]:

import datetime
from googleapiclient.discovery import build
import pandas as pd
from pymongo import MongoClient
import streamlit as st
from sqlalchemy import create_engine
from datetime import datetime
import pymysql

# Create a SQLAlchemy engine
engine = create_engine('mysql+pymysql://root:12345@localhost/youtube_anlysis_db')

# In[3]:


api_key = 'AIzaSyDcMF_PnW0Gw4W-ohLpDmxL7IS02xjOHw0'


# In[ ]:



channel_ids = []  # Move the list definition outside the function

def main():
    N = st.number_input("Enter the number of channels", min_value=1, step=1, value=1, format="%d")
    for i in range(int(N)):
        channel = st.text_input(f"Enter Channel ID {i+1}")
        channel_ids.append(channel)
    
    if st.button("Submit"):
        process_channel_ids()
        get_video_details(api_key, channel_ids)
        migrate_data()
        results = query_execution()
        for query_name, result_df in results.items():
            st.subheader(query_name)
            st.table(result_df)
        


def process_channel_ids():
    st.write("Channel IDs:", channel_ids)
    

youtube = build('youtube', 'v3', developerKey=api_key)
client = MongoClient('mongodb://localhost:27017/')
db = client['youtube_stats']
collection = db['channel_stats']


# In[6]:


from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from pymongo import MongoClient
import isodate


def get_channel_info(youtube, channel_ids):
    try:
        request = youtube.channels().list(
            part='snippet,contentDetails,statistics',
            id=','.join(channel_ids)
        )
        response = request.execute()

        channel_info = []

        for item in response['items']:
            channel_id = item['id']
            channel_name = item['snippet']['title']
            data = {
                'Channel_name': channel_name,
                'channel_id': channel_id,
                'Subscribers': item['statistics']['subscriberCount'],
                'channel_description': item['snippet']['description'],
                'Views': item['statistics']['viewCount'],
                'playlist_id': item['contentDetails']['relatedPlaylists']['uploads']
            }
            channel_info.append(data)
        return channel_info

    except (HttpError, KeyError) as e:
        print(f"An error occurred while retrieving channel information: {str(e)}")
        return None


def get_video_details(api_key, channel_ids):
    # Initialize the YouTube API client
    youtube = build('youtube', 'v3', developerKey=api_key)

    # Connect to MongoDB
    client = MongoClient('mongodb://localhost:27017/')

    # Access the database
    db = client['youtube_stats']

    # Access the collection
    collection = db['channel_stats']

    for channel_id in channel_ids:
        try:
            # Retrieve channel information
            channel_info = get_channel_info(youtube, [channel_id])

            if not channel_info:
                continue

            channel_data = channel_info[0]
            playlist_id = channel_data['playlist_id']

            if not playlist_id:
                print(f"No playlist ID found for channel ID {channel_id}. Skipping...")
                continue

            # Retrieve video IDs for the channel
            video_ids = get_all_videos(youtube, playlist_id)

            all_video_stats = []
            count = 1

            # Batch process video IDs
            for video_id in video_ids:
                try:
                    video_response = youtube.videos().list(
                        part='snippet,statistics,contentDetails',
                        id=video_id
                    ).execute()

                    video = video_response['items'][0]

                    video_stats = {f'video_{count}': {
                        'Video_Id': video_id,
                        'video_name': video['snippet']['title'],
                        'video_description': video['snippet']['description'],
                        'playlist_id': video['snippet'].get('playlistId', ''),
                        'Published_At': video['snippet']['publishedAt'],
                        'Views': video['statistics'].get('viewCount', 0),
                        'Likes': video['statistics'].get('likeCount', 0),
                        'dislike_count': int(video['statistics'].get('dislikeCount', 0)),
                        'favorite_count': int(video['statistics'].get('favoriteCount', 0)),
                        'tags': video['snippet'].get('tags', []),
                        'duration': str(isodate.parse_duration(video['contentDetails']['duration'])),
                        'Comments_count': video['statistics'].get('commentCount', 0),
                        'thumbnail': video['snippet']['thumbnails']['default']['url'],
                        'caption_status': video['snippet'].get('caption', 0),
                        'comments': []
                    }}

                    # Retrieve comments for the video
                    try:
                        comment_response = youtube.commentThreads().list(
                            part='snippet',
                            videoId=video_id,
                            textFormat='plainText',
                            maxResults=100
                        ).execute()

                        # Iterate over the comments
                        for item in comment_response['items']:
                            comment_id = item['id']
                            comment_text = item['snippet']['topLevelComment']['snippet']['textDisplay']
                            comment_author = item['snippet']['topLevelComment']['snippet']['authorDisplayName']
                            comment_published_at = item['snippet']['topLevelComment']['snippet']['publishedAt']
                            comment_data = {
                                'comment_id': comment_id,
                                'comment_text': comment_text,
                                'Comment_Author': comment_author,
                                'Comment_PublishedAt': comment_published_at
                            }
                            video_stats[f'video_{count}']['comments'].append(comment_data)

                    except HttpError as e:
                        if e.resp.status == 403 and 'commentsDisabled' in str(e):
                            print(f"Comments are disabled for video ID {video_id}. Skipping comments retrieval...")
                        else:
                            error_details = e.content.decode('utf-8')
                            print(f"An error occurred while retrieving comments for video ID {video_id}: {error_details}")

                    all_video_stats.append(video_stats)
                    count += 1
                except HttpError as e:
                    error_details = e.content.decode('utf-8')
                    print(f"An error occurred while retrieving video details for video ID {video_id}: {error_details}")

            # Update the channel document in MongoDB
            filter_query = {'channel_id': channel_id}
            update_query = {'$set': {'channel_info': channel_data, 'video_info': all_video_stats}}
            collection.update_one(filter_query, update_query, upsert=True)

        except HttpError as e:
            error_details = e.content.decode('utf-8')
            print(f"An error occurred while retrieving channel information for channel ID {channel_id}: {error_details}")


def get_all_videos(youtube, playlist_id):
    videos = []

    next_page_token = None

    while True:
        try:
            playlist_items_response = youtube.playlistItems().list(
                part='contentDetails',
                playlistId=playlist_id,
                maxResults=50,
                pageToken=next_page_token
            ).execute()

            videos.extend(playlist_items_response['items'])

            next_page_token = playlist_items_response.get('nextPageToken')

            if not next_page_token:
                break

        except HttpError as e:
            error_details = e.content.decode('utf-8')
            print(f"An error occurred while retrieving videos from playlist {playlist_id}: {error_details}")
            break

    video_ids = [video['contentDetails']['videoId'] for video in videos]
    return video_ids




# In[2]:





# In[38]:



def migrate_data():
    # Connect to MongoDB
    mongo_client = MongoClient('mongodb://localhost:27017/')

    # Access the MongoDB database
    mongo_db = mongo_client['youtube_stats']

    # Access the MongoDB collection
    mongo_collection = mongo_db['channel_stats']

    # Connect to MySQL
    mysql_conn = pymysql.connect(
        host='localhost',
        user='root',
        password='12345',
        database='youtube_anlysis_db'
    )

    try:
        mongo_cursor = mongo_collection.find()

        # Migrate data to MySQL
        mysql_cursor = mysql_conn.cursor()

        # Retrieve data from MongoDB
        for doc in mongo_cursor:
            channel_info = doc.get('channel_info', {})
            channel_name = channel_info.get('Channel_name')
            channel_id = channel_info.get('channel_id')
            subscribers = channel_info.get('Subscribers')
            views = channel_info.get('Views')
            playlist_id = channel_info.get('playlist_id')

            # Insert channel data into MySQL
            mysql_query = f"INSERT INTO channel (Channel_Id, Channel_Name, Subscribers_count, Channel_views, Playlist_ID) " \
                          f"VALUES ('{channel_id}', '{channel_name}', '{subscribers}', '{views}', '{playlist_id}')"
            mysql_cursor.execute(mysql_query)
            if channel_name and channel_id:
                video_info = doc.get('video_info', [])

            for video in video_info:
                video_data = video.get(list(video.keys())[0], {})
                video_id = video_data.get('Video_Id')
                title = video_data.get('video_name')
                video_description = video_data.get('video_description')
                datetime_str = str(video_data.get('Published_At'))
                datetime_str = datetime_str[:-1]  # Remove the 'Z' character
                datetime_obj = datetime.strptime(datetime_str, '%Y-%m-%dT%H:%M:%S')
                published_at = datetime_obj.strftime('%Y-%m-%d %H:%M:%S')
                views = video_data.get('Views')
                likes = video_data.get('Likes')
                dislike_count = video_data.get('dislike_count')
                comments_count = video_data.get('Comments_count')

                # Insert video data into MySQL
                mysql_query = "INSERT INTO video (channel_id, video_id, playlist_id, video_name, video_description, published_date, view_count, like_count, dislike_count, comment_count) " \
                              "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"
                mysql_cursor.execute(mysql_query, (channel_id, video_id, playlist_id, title, video_description, published_at, views, likes, dislike_count, comments_count))
                mysql_conn.commit()
                mysql_cursor.execute("SELECT LAST_INSERT_ID()")
                #video_id = mysql_cursor.fetchone()[0]
                comments = video_data.get('comments', [])
                for comment in comments:
                    comment_id = comment['comment_id']
                    comment_text = comment['comment_text']
                    comment_author = comment['Comment_Author']
                    datetime_str = str(comment['Comment_PublishedAt'])
                    datetime_str = datetime_str[:-1]  # Remove the 'Z' character
                    datetime_obj = datetime.strptime(datetime_str, '%Y-%m-%dT%H:%M:%S')

                    comment_published_at = datetime_obj.strftime('%Y-%m-%d %H:%M:%S')

                    # Insert comment data into MySQL
                    mysql_query = "INSERT INTO comment (comment_id, video_id, comment_text, comment_author, comment_published_date) " \
                                  "VALUES (%s, %s, %s, %s, %s)"
                    mysql_cursor.execute(mysql_query, (comment_id, video_id, comment_text, comment_author, comment_published_at))
        
                    mysql_conn.commit()
        print("Data migration from MongoDB to MySQL completed successfully.")

    except Exception as e:
        print(f"An error occurred during data migration: {str(e)}")

    finally:
        # Close the connections
        mongo_client.close()
        mysql_cursor.close()
        mysql_conn.close()

# Perform the data migration



# In[3]:


def query_execution():
    mongo_client = MongoClient('mongodb://localhost:27017/')

    # Access the MongoDB database
    mongo_db = mongo_client['youtube_stats']

    # Access the MongoDB collection
    mongo_collection = mongo_db['channel_stats']

    
# Connect to MySQL
    mysql_conn = pymysql.connect(
                host='localhost',
                user='root',
                password='12345',
                database='youtube_anlysis_db'
    )

    # Create a cursor
    mysql_cursor = mysql_conn.cursor()

    # Query 1: Names of all videos and their corresponding channels
    # Query 1: Names of all videos and their corresponding channels
    query_results = {}
    query1 = '''
    SELECT video.video_name, channel.channel_name
    FROM video
    JOIN channel ON video.channel_id = channel.channel_id
    '''
    df1 = pd.read_sql(query1, engine)
    query_results['Query 1: Names of all videos and their corresponding channels'] = df1
    

    # Query 2: Channels with the most number of videos
    query2 = '''
    SELECT channel.channel_name, COUNT(video.video_id) AS video_count
    FROM channel
    JOIN video ON channel.channel_id = video.channel_id
    GROUP BY channel.channel_name
    ORDER BY video_count DESC
    '''
    df2 = pd.read_sql(query2, engine)
    
    query_results['Query 2: Channels with the most number of videos'] = df2

    # Query 3: Top 10 most viewed videos and their respective channels
    query3 = '''
    SELECT video.video_name, channel.channel_name, video.view_count
    FROM video
    JOIN channel ON video.channel_id = channel.channel_id
    ORDER BY  video.view_count DESC
    LIMIT 10
    '''
    df3 = pd.read_sql(query3, engine)
    st.subheader("Top 10 most viewed videos and their respective channels")
    st.table(df3)
    query_results['Query 3: Top 10 most viewed videos and their respective channels'] = df3
    

    # Query 4: Number of comments on each video and their corresponding names
    query4 = '''
    SELECT video.video_name, COUNT(comment.comment_id) AS comment_count
    FROM video
    JOIN comment ON video.video_id = comment.video_id
    GROUP BY video.video_name
    '''
    df4 = pd.read_sql(query4, engine)
    st.subheader("Number of comments on each video and their corresponding names")
    st.table(df4)
    query_results['Query 4: Number of comments on each video and their corresponding names'] = df4

    # Query 5: Videos with the highest number of likes and their corresponding channel names
    query5 = '''
    SELECT video.video_name, channel.channel_name, video.Like_count
    FROM video
    JOIN channel ON video.channel_id = channel.channel_id
    ORDER BY video.Like_count DESC;
    '''
    df5 = pd.read_sql(query5, engine)
    
    query_results['Query 5: Videos with the highest number of likes and their corresponding channel names'] = df5

    # Query 6: Total number of likes and dislikes for each video and their corresponding names
    query6 = '''

    SELECT video.video_name, SUM(video.Like_count) AS total_likes, SUM(video.dislike_count) AS total_dislikes
    FROM video
    GROUP BY video.video_name;
    '''
    df6 = pd.read_sql(query6, engine)
  
    query_results['Total number of likes and dislikes for each video and their corresponding names'] = df6

    # Query 7: Total number of views for each channel and their corresponding names
    query7 = '''
    SELECT channel.channel_name, SUM(video.View_count) AS total_views
    FROM channel
    JOIN video ON channel.channel_id = video.channel_id
    GROUP BY channel.channel_name;
    '''
    df7 = pd.read_sql(query7, engine)
   
    query_results['Total number of views for each channel and their corresponding names'] = df7

    # Query 8: Names of channels that published videos in the year 2022
    query8 = '''
    SELECT channel.channel_name
    FROM channel
    JOIN video ON channel.channel_id = video.channel_id
    WHERE YEAR(video.published_date) = 2022
    GROUP BY channel.channel_name
    '''
    df8 = pd.read_sql(query8, engine)
   
    query_results['Names of channels that published videos in the year 2022'] = df8

    # Query 9: Average duration of all videos in each channel and their corresponding names
    query9 = '''
    SELECT channel.channel_name, AVG(video.duration) AS average_duration
    FROM channel
    JOIN video ON channel.channel_id = video.channel_id
    GROUP BY channel.channel_name
    '''
    df9 = pd.read_sql(query9, engine)
    
    query_results['Average duration of all videos in each channel and their corresponding names'] = df9

    # Query 10: Videos with the highest number of comments and their corresponding channel names
    query10 = '''
    SELECT video.video_name, channel.channel_name, COUNT(comment.comment_id) AS comment_count
    FROM video
    JOIN channel ON video.channel_id = channel.channel_id
    JOIN comment ON video.video_id = comment.video_id
    GROUP BY video.video_name
    ORDER BY comment_count DESC
    LIMIT 10;
    '''
    df10 = pd.read_sql(query10, engine)
    
    query_results['Videos with the highest number of comments and their corresponding channel names'] = df10
    
    
    mysql_cursor.execute('TRUNCATE TABLE channel')
    mysql_cursor.execute('TRUNCATE TABLE video')
    mysql_cursor.execute('TRUNCATE TABLE comment')
    # Close the MySQL connection
    mysql_cursor.close()
    mysql_conn.close()
    mongo_collection.drop()
    # Perform further processing or actions with the channel IDs
    return query_results
if __name__ == '__main__':
    main()




# In[4]:





# In[5]:
st.stop()

