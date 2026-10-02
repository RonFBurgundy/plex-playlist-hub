import { useState, useEffect, useRef, useCallback } from 'react';
import type { AudioPreviewTrack } from '@/types/models';

export interface UseAudioPlayerReturn {
  currentTrack: AudioPreviewTrack | null;
  isPlaying: boolean;
  progress: number; // 0 to 100
  duration: number; // seconds
  currentTime: number; // seconds
  play: (track: AudioPreviewTrack) => void;
  pause: () => void;
  toggle: (track: AudioPreviewTrack) => void;
  stop: () => void;
  seek: (fraction: number) => void;
}

export function useAudioPlayer(): UseAudioPlayerReturn {
  const [currentTrack, setCurrentTrack] = useState<AudioPreviewTrack | null>(null);
  const [isPlaying, setIsPlaying] = useState<boolean>(false);
  const [progress, setProgress] = useState<number>(0);
  const [duration, setDuration] = useState<number>(0);
  const [currentTime, setCurrentTime] = useState<number>(0);

  const audioRef = useRef<HTMLAudioElement | null>(null);

  useEffect(() => {
    const audio = new Audio();
    audioRef.current = audio;

    const onTimeUpdate = () => {
      if (audio.duration && !isNaN(audio.duration)) {
        setDuration(audio.duration);
        setCurrentTime(audio.currentTime);
        setProgress((audio.currentTime / audio.duration) * 100);
      }
    };

    const onEnded = () => {
      setIsPlaying(false);
      setProgress(0);
      setCurrentTime(0);
    };

    const onPause = () => {
      setIsPlaying(false);
    };

    const onPlay = () => {
      setIsPlaying(true);
    };

    const onError = () => {
      setIsPlaying(false);
      setProgress(0);
    };

    audio.addEventListener('timeupdate', onTimeUpdate);
    audio.addEventListener('ended', onEnded);
    audio.addEventListener('pause', onPause);
    audio.addEventListener('play', onPlay);
    audio.addEventListener('error', onError);

    return () => {
      audio.removeEventListener('timeupdate', onTimeUpdate);
      audio.removeEventListener('ended', onEnded);
      audio.removeEventListener('pause', onPause);
      audio.removeEventListener('play', onPlay);
      audio.removeEventListener('error', onError);
      audio.pause();
      audio.src = '';
    };
  }, []);

  const play = useCallback((track: AudioPreviewTrack) => {
    if (!audioRef.current || !track.preview_url) return;

    if (currentTrack?.id === track.id && audioRef.current.src) {
      audioRef.current.play().catch(() => {});
      setIsPlaying(true);
      return;
    }

    setCurrentTrack(track);
    setProgress(0);
    setCurrentTime(0);
    audioRef.current.src = track.preview_url;
    audioRef.current.play().catch(() => {});
    setIsPlaying(true);
  }, [currentTrack]);

  const pause = useCallback(() => {
    if (audioRef.current) {
      audioRef.current.pause();
      setIsPlaying(false);
    }
  }, []);

  const toggle = useCallback((track: AudioPreviewTrack) => {
    if (currentTrack?.id === track.id && isPlaying) {
      pause();
    } else {
      play(track);
    }
  }, [currentTrack, isPlaying, pause, play]);

  const stop = useCallback(() => {
    if (audioRef.current) {
      audioRef.current.pause();
      audioRef.current.src = '';
      setIsPlaying(false);
      setCurrentTrack(null);
      setProgress(0);
      setCurrentTime(0);
    }
  }, []);

  const seek = useCallback((fraction: number) => {
    if (audioRef.current && audioRef.current.duration) {
      const targetTime = Math.max(0, Math.min(1, fraction)) * audioRef.current.duration;
      audioRef.current.currentTime = targetTime;
      setCurrentTime(targetTime);
      setProgress(fraction * 100);
    }
  }, []);

  return {
    currentTrack,
    isPlaying,
    progress,
    duration,
    currentTime,
    play,
    pause,
    toggle,
    stop,
    seek,
  };
}
