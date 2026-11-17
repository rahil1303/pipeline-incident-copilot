with tracks as (
    select * from {{ ref('stg_tracks') }}
),

enriched as (
    select
        *,
        round(duration_ms / 60000.0, 2) as duration_minutes,
        case
            when energy >= 0.5 and valence >= 0.5 then 'Happy/Energetic'
            when energy >= 0.5 and valence < 0.5  then 'Angry/Turbulent'
            when energy < 0.5  and valence >= 0.5 then 'Chill/Peaceful'
            else                                       'Sad/Melancholic'
        end as mood_quadrant,
        case
            when popularity >= 80 then 'viral'
            when popularity >= 60 then 'popular'
            when popularity >= 40 then 'moderate'
            else                       'niche'
        end as popularity_tier,
        case
            when danceability >= 0.75 then 'high'
            when danceability >= 0.4  then 'medium'
            else                           'low'
        end as danceability_bucket
    from tracks
)

select * from enriched
