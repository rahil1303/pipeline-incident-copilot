with enriched as (
    select * from {{ ref('int_tracks_enriched') }}
),

summary as (
    select
        mood_quadrant,
        popularity_tier,
        count(*)                                        as track_count,
        round(avg(danceability)::numeric, 3)            as avg_danceability,
        round(avg(energy)::numeric, 3)                  as avg_energy,
        round(avg(valence)::numeric, 3)                 as avg_valence,
        round(avg(tempo)::numeric, 1)                   as avg_tempo,
        round(avg(loudness)::numeric, 2)                as avg_loudness,
        round(avg(acousticness)::numeric, 3)            as avg_acousticness,
        round(avg(instrumentalness)::numeric, 3)        as avg_instrumentalness,
        round(avg(speechiness)::numeric, 3)             as avg_speechiness,
        round(avg(liveness)::numeric, 3)                as avg_liveness,
        round(avg(popularity)::numeric, 1)              as avg_popularity,
        max(popularity)                                 as max_popularity,
        round(avg(duration_minutes)::numeric, 2)        as avg_duration_minutes
    from enriched
    group by 1, 2
)

select * from summary
order by mood_quadrant, popularity_tier
