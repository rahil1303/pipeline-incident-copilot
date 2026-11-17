with source as (
    select * from {{ ref('raw_tracks') }}
),

cleaned as (
    select
        track_id,
        track_name,
        artists                                         as artist_names,
        album_name,
        track_genre,
        popularity,
        duration_ms,
        explicit                                        as is_explicit,
        danceability,
        energy,
        loudness,
        speechiness,
        acousticness,
        instrumentalness,
        liveness,
        valence,
        tempo,
        key,
        mode,
        time_signature,
        {{ dbt_schema_aware_pipeline.current_timestamp_fn() }} as loaded_at
    from source
    where track_id is not null
      and track_name is not null
      AND tempo > 0
)

select * from cleaned