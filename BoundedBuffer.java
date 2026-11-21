// SPDX-License-Identifier: MIT

import java.util.concurrent.locks.Condition;
import java.util.concurrent.locks.ReentrantLock;

public class BoundedBuffer<T> {

    private final Object[] items;
    private int putIndex;
    private int takeIndex;
    private int count;

    private final ReentrantLock lock = new ReentrantLock();
    private final Condition notEmpty = lock.newCondition();
    private final Condition notFull = lock.newCondition();

    public BoundedBuffer(int capacity) {
        if (capacity <= 0) {
            throw new IllegalArgumentException("capacity must be positive");
        }
        this.items = new Object[capacity];
    }

    public void put(T item) throws InterruptedException {
        if (item == null) {
            throw new NullPointerException();
        }
        lock.lockInterruptibly();
        try {
            while (count == items.length) {
                notFull.await();
            }
            items[putIndex] = item;
            putIndex = (putIndex + 1) % items.length;
            count++;
            notEmpty.signal();
        } finally {
            lock.unlock();
        }
    }

    public T take() throws InterruptedException {
        lock.lockInterruptibly();
        try {
            while (count == 0) {
                notEmpty.await();
            }
            @SuppressWarnings("unchecked")
            T item = (T) items[takeIndex];
            items[takeIndex] = null;
            takeIndex = (takeIndex + 1) % items.length;
            count--;
            notFull.signal();
            return item;
        } finally {
            lock.unlock();
        }
    }

    public void add(T item) throws InterruptedException {
        put(item);
    }

    public T remove() throws InterruptedException {
        return take();
    }

    public void enqueue(T item) throws InterruptedException {
        put(item);
    }

    public T dequeue() throws InterruptedException {
        return take();
    }

    public boolean offer(T item) {
        if (item == null) {
            throw new NullPointerException();
        }
        lock.lock();
        try {
            if (count == items.length) {
                return false;
            }
            items[putIndex] = item;
            putIndex = (putIndex + 1) % items.length;
            count++;
            notEmpty.signal();
            return true;
        } finally {
            lock.unlock();
        }
    }

    public T poll() {
        lock.lock();
        try {
            if (count == 0) {
                return null;
            }
            @SuppressWarnings("unchecked")
            T item = (T) items[takeIndex];
            items[takeIndex] = null;
            takeIndex = (takeIndex + 1) % items.length;
            count--;
            notFull.signal();
            return item;
        } finally {
            lock.unlock();
        }
    }

    public int size() {
        lock.lock();
        try {
            return count;
        } finally {
            lock.unlock();
        }
    }

    public boolean isEmpty() {
        return size() == 0;
    }

    public boolean isFull() {
        lock.lock();
        try {
            return count == items.length;
        } finally {
            lock.unlock();
        }
    }
}